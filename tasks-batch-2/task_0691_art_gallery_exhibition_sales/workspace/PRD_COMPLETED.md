# Art Gallery Exhibition Sales API — Product Requirements Document

## 1. Introduction

This document specifies the Art Gallery Exhibition Sales API, the system of record for a contemporary gallery that takes works on consignment, mounts exhibitions, sells and leases art, runs opening receptions, lends pieces to other institutions, and settles what it owes the artists it represents. A single gallery is the root of everything: artists are registered against it, artworks are consigned by those artists, exhibitions are scheduled on its floor plan, and every sale, payment plan, lease, opening event, RSVP, loan, and payout traces back to that gallery. The product's hardest problems are not the individual records but the relationships between them — a finite wall map that must never be over-committed, a consignment ledger that has to reconcile what was promised at reservation against what is actually owed at settlement, and a set of cascading state changes where finalizing one sale can quietly retire an artwork, free a wall slot, and credit an artist's account in a single atomic step.

Three concerns recur throughout. First, **scarcity**: wall capacity on a show, seats at an opening, and an artwork's loan calendar are all finite resources that the system reserves, commits, and releases. Second, **money that changes shape over time**: a consignment split is estimated provisionally when a work is reserved and recomputed for real when the buyer has paid in full, and an artist's payable balance is the running difference between what has accrued and what has been disbursed. Third, **time**: a logical clock — not wall-clock time — drives installment due dates, RSVP deadlines, lease accrual, and loan-overdue evaluation, so that scenarios can be exercised deterministically. The sections that follow define the global contract first, then the business workflows where these concerns interleave.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, envelopes, and cross-cutting principles that govern every endpoint.

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming their operational capacity. If either header is missing, or if `X-User-Role` is not one of the recognized roles, the request is rejected with `ERR_UNAUTHENTICATED`. When the headers are well formed but the named role is not permitted to perform the requested operation, the request is rejected with `ERR_FORBIDDEN`.

The system recognizes exactly four roles: `GalleryAdmin`, `Registrar`, `SalesAssociate`, and `Artist`.

A `GalleryAdmin` is the gallery operator with the broadest surface — gallery and artist setup, exhibition lifecycle, lease termination, the payout lifecycle, reporting, and the test clock. A `Registrar` is the collections registrar who owns provenance, consignment intake, wall-map placement, and loan and insurance operations. A `SalesAssociate` is the front-of-house role that owns sales, payments, shipping, payment plans, leases, and RSVPs. For all three of these roles, `X-User-ID` is an opaque operator identifier that is not tied to any persisted entity; the server may accept and log it but never compares it to any record's `id`.

An `Artist`, by contrast, is entity-backed. When `X-User-Role` is `Artist`, `X-User-ID` is the `id` of the acting `Artist` record. An `Artist` has read-only visibility, and ownership checks on any resource that references an artist compare that resource's artist foreign key to `X-User-ID` — an artist sees their own ledger, their own consigned artworks (reachable by filtering on `artist_id`), the sales of those artworks, and their own payouts, plus read context on exhibitions, opening events, and the gallery itself. On a single-resource read of an artist, artwork, sale, or payout that exists but is not owned by the acting artist, the request is rejected with `ERR_FORBIDDEN` (the resource is found to exist first, then ownership is denied); on a list read, non-owned rows are silently filtered out rather than erroring. The gallery, exhibition, opening-event, and wall-slot reads an artist is granted apply no per-row ownership filter.

### 2.2. API Response Structure

#### Standard Success Response Format

All successful API responses (those with 2xx status codes) follow this standard envelope format in their JSON body:

```json
{
  "meta": {
    "api_request_id": "req_RANDOMALPHANUM123456",
    "api_request_timestamp": "2025-05-24T10:30:00.123Z",
    "limit": 10,
    "offset": 0,
    "total_count": 100,
    "has_more": true
  },
  "response_type": "object" | "array",
  "data": { }
}
```

- The `api_request_id` is a server-generated unique identifier for the request that starts with `req_`.
- The `api_request_timestamp` is a server-generated ISO 8601 UTC timestamp with three fractional digits.
- The `response_type` is either "object" for a single resource or "array" for a list of resources.
- The `data` field contains the resource object or an array of resource objects. For 2xx responses with no data, it contains an empty object. Unless otherwise noted, operations that create or modify a resource will return the created or updated resource object in the data field.
- Pagination-related fields in `meta` (`limit`, `offset`, `total_count`, `has_more`) are included for list endpoints.

#### Standard Error Response Format

All error API responses (4xx status codes) follow this standard envelope format:

```json
{
  "meta": {
    "api_request_id": "req_RANDOMALPHANUM123456",
    "api_request_timestamp": "2025-05-24T10:30:00.123Z"
  },
  "response_type": "error",
  "data": {
    "error_id": "UNIQUE_ERROR_IDENTIFIER_STRING",
    "message": "A human-readable explanation of the error."
  }
}
```

- The `meta` object for error responses contains only `api_request_id` and `api_request_timestamp`.
- The `error_id` is a unique, machine-readable string that identifies the specific error.
- The `message` provides a human-readable explanation of what went wrong.

---

### 2.3. Pagination

List endpoints are paginated through two query parameters. `limit` caps the number of items returned; it defaults to 10, may not be below 1, and may not exceed 100. `offset` is the number of items to skip and defaults to 0, with a minimum of 0. A `limit` below 1 or above 100, or a negative `offset`, is rejected with `ERR_VALIDATION_PAGINATION`.

Unless a specific endpoint states otherwise, every list is returned sorted by `created_at` in ascending order, with ties (records created within the same wall-clock millisecond) broken by ascending creation/insertion order so the ordering is fully deterministic. List endpoints accept equality filters on the foreign-key and status fields noted per resource; unknown query parameters are ignored.

Each list response carries `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope, where `total_count` is the total number of matching items before pagination and `has_more` indicates whether items remain beyond the current page.

### 2.4. Resource Topology, Identity, and Common Properties

The catalogue is flat: galleries, artists, artworks, exhibitions, wall slots, sales, payment plans, leases, opening events, RSVPs, loans, and payouts are all top-level collections. A child record is tied to its gallery not through a nested URL but through a foreign key carried in the request body on creation and offered as a filter on its list endpoint. So an `Artist` create supplies its `gallery_id`; an `Artwork` create supplies both `gallery_id` and the consigning `artist_id`; a `Sale` create supplies `gallery_id` and `artwork_id`. For sub-resources created beneath a parent in the URL — wall slots, payment plans, leases, opening events, RSVPs, loans, and payouts — the `gallery_id` is derived from the parent resource rather than supplied by the client.

Every resource carries a server-minted `id` that is a UUID with no type prefix, used for identity only, and a `created_at` timestamp formatted as ISO 8601 UTC with three fractional digits (e.g. `2026-04-01T00:00:00.000Z`); `created_at` and `updated_at` are stamped from real wall-clock time at the moment of the write, not from the logical clock. Most resources additionally carry `updated_at` (an ISO 8601 UTC timestamp refreshed on every mutation) and `version` (an integer that begins at 1 and increments by one on every mutation). This three-fractional-digit form applies only to these record-keeping stamps (`created_at`, `updated_at`) and to the `api_request_timestamp` of the envelope; every business *instant* field a client supplies and the system echoes back — `clock_utc`, an exhibition's `opens_utc`/`closes_utc`, an opening event's `starts_utc`/`rsvp_deadline_utc`, a payment plan's `first_due_utc`, a lease's `starts_utc`, a loan's `out_utc`/`due_utc`/`returned_utc`, and a provenance entry's `at_utc` — is instead rendered with no fractional digits in the form `2026-04-01T00:00:00Z`. Every entity in this system — Gallery, Artist, Artwork, Exhibition, WallSlot, Sale, PaymentPlan, LeaseAgreement, OpeningEvent, Rsvp, Loan, and Payout — carries the full set: `id`, `created_at`, `updated_at`, and `version`.

Derived fields are computed live on each read rather than stored: an exhibition's `slots_occupied`/`slots_available`, a payment plan's `missed_installment_count`, a lease's `months_accrued`/`rent_accrued_cents`/`buyout_price_cents`, an opening event's `confirmed_count`/`waitlist_count`, and an artist's three ledger figures are all recalculated from the current state and clock when the resource is serialized. Because these figures are recomputed on read, the act of recomputing them does not by itself bump the carrying resource's `version` or refresh its `updated_at`; in particular, settling a sale (which causes that artist's accrued ledger to change) and completing or reversing a payout (which changes the paid figure) do not touch the affected artist record's `version` or `updated_at` — only an explicit mutation of a resource bumps that resource's own `version`.

### 2.5. Nested Retrieval and Existence Ordering

Some reads and writes name a parent in the path — for example, listing or placing wall slots under an exhibition. The system validates path and body references left to right: the gallery scope first, then the artwork, exhibition, sale, plan, lease, event, RSVP, loan, or payout named after it. The first reference that does not resolve within scope yields `ERR_NOT_FOUND`, and that check happens before any state, concurrency, or business rule is evaluated.

### 2.6. Validation Ordering

When several conditions could reject the same request, they are evaluated in a fixed priority order so that the returned error is deterministic. The order is: (1) authentication of the headers, failing with `ERR_UNAUTHENTICATED`; (2) authorization of the role for the operation, failing with `ERR_FORBIDDEN`; (3) existence of resources named in the URL **path** (the path parent), failing with `ERR_NOT_FOUND`; (4) well-formedness of the request body — required fields present, of the correct JSON type, with enum values legal and numeric constraints honored — failing with `ERR_INVALID_REQUEST`; (4b) existence of resources referenced by **body** foreign keys (e.g. a sale's `gallery_id`/`artwork_id`/`exhibition_id`, an artwork's `gallery_id`/`artist_id`), failing with `ERR_NOT_FOUND`; (5) the target resource being in a legal state for the requested transition, failing with `ERR_INVALID_STATE`; (6) the optimistic-concurrency version check on supersede creates, failing with `ERR_STALE_VERSION`; and then the domain-specific business rules described throughout §3, in this relative order — the artist-suspension gate (`ERR_ARTIST_SUSPENDED`), loan coverage adequacy (`ERR_INSUFFICIENT_COVERAGE`), temporal-overlap conflicts (`ERR_SCHEDULE_CONFLICT`), wall-map capacity and position uniqueness (`ERR_WALL_CAPACITY_EXCEEDED`), the RSVP deadline (`ERR_RSVP_CLOSED`), event capacity handling, the no-overpayment guard (`ERR_OVERPAYMENT`), and the payout funds guard (`ERR_NO_PAYABLE_BALANCE`). Earlier checks always mask later ones: a request that is both unauthorized and references a missing resource returns `ERR_FORBIDDEN`, never `ERR_NOT_FOUND`.

### 2.7. The Logical Clock

The system runs on a logical clock rather than wall-clock time. At server startup the clock reads exactly `2026-04-01T00:00:00Z`, and it stays at that default until a `GalleryAdmin` sets it; the system never falls back to real time. An admin-only test-driving capability advances the clock to a supplied UTC instant carried as `to_iso8601`, and the response returns the resulting `clock_utc`. Setting the clock applies the new instant to every gallery's `clock_utc` and re-derives every clock-dependent figure on the next read — installment due dates and missed counts, lease months accrued and buyout price, loan overdue eligibility, and RSVP deadlines. The clock value is also stamped onto records that capture "now": a loan's `returned_utc`, a provenance entry's `at_utc`, and the like.

### 2.8. Monetary Precision and Rounding

All monetary amounts are stored and returned as integer cents. Wherever a percentage or basis-point factor is applied — sales tax, consignment splits, lease-rent credit — the result is rounded to the nearest whole cent using the round-half-up convention (a value exactly at the half rounds up). Basis points express hundredths of a percent, so 10000 basis points is 100% and a factor of `x` basis points means multiplying by `x` and dividing by 10000. Counts and seat tallies are whole integers; lease months are whole months. Two derived balances are explicitly floored at zero and may never go negative: an artist's payable balance and a lease buyout price.

### 2.9. Optimistic Concurrency on Supersede Creates

Two write operations are guarded against acting on a stale view of their parent, because each legitimately supersedes a snapshot the client had previously read.

Placing a wall slot on an exhibition requires the field `expected_exhibition_version` in the request body, carrying the `version` of the target `Exhibition` that the client last observed. If that value does not equal the exhibition's current `version`, the placement is rejected with `ERR_STALE_VERSION` at HTTP 412. This is what makes it safe for a new placement to consume the last open slot on the floor: if another placement has already filled that slot and bumped the exhibition's `version`, a create issued against the now-outdated view is rejected rather than silently overwriting the floor plan.

Posting a payment against a sale requires the field `expected_sale_version` in the request body, carrying the `version` of the target `Sale` that the client last observed. If that value does not equal the sale's current `version`, the payment is rejected with `ERR_STALE_VERSION` at HTTP 412, preventing a client from posting against a collected-amount snapshot that has since moved. No other endpoint accepts a version field, and where these two endpoints succeed they increment the parent's `version` as part of the write.

### 2.10. The Consignment Ledger Principle

Each artist carries three ledger figures, all derived and never stored as free input: `ledger_accrued_cents`, the cumulative artist share from settled sales of that artist's artworks computed with the final split; `ledger_paid_cents`, the cumulative amount moved into completed payouts for that artist; and `ledger_payable_cents`, what the gallery still owes, which is the accrued amount minus the paid amount, floored at zero. At every moment the accrued amount equals the paid amount plus the payable amount — a conservation invariant the system preserves through accruals, payout completions, and payout reversals alike. Money accrues to the artist only at settlement, never at reservation: the provisional split that a sale shows while reserved is informational and is not added to the ledger.

### 2.11. The Wall Map and Loan Calendar as Booking Ledgers

Two scarce resources behave like booking calendars. An exhibition's floor plan has a fixed `wall_capacity`; the live `slots_occupied` is the number of wall slots currently `PLACED` for the show and `slots_available` is `wall_capacity` minus `slots_occupied`, never negative. An artwork's loan history is likewise a calendar: every loan ever recorded for a work — outstanding, overdue, or already returned — continues to reserve its window, so the gallery can reconstruct exactly when a piece was unavailable. The temporal-overlap rules that protect both calendars are detailed in §3 alongside the placement and loan workflows.

## 3. Business Logic & Workflows

### 3.1. Establishing the Gallery and Its Artists

Everything begins with a gallery, created by a `GalleryAdmin` who supplies a `name`, a two-letter uppercase `home_state_code` identifying the state the gallery sells from, and a `sales_tax_rate_bps` giving the default sales-tax rate in basis points (so 875 means 8.75%), which must be between 0 and 2000 inclusive. Two optional fields tune fiscal behavior: `resale_exempt_threshold_cents`, which defaults to 0 and must be at least 0, and `default_consignment_split_bps`, which defaults to 5000 — meaning the artist keeps 50% of net by default — and must be between 0 and 10000 inclusive. The gallery's `clock_utc` is not a stored per-gallery field but a live reflection of the single shared logical clock: every gallery read returns the current clock value (the startup default until a `GalleryAdmin` sets it), so all galleries always report the same `clock_utc`. The `home_state_code` must be exactly two uppercase letters; the gallery serialization returns `name`, `home_state_code`, `sales_tax_rate_bps`, `resale_exempt_threshold_cents`, `default_consignment_split_bps`, and `clock_utc`.

A `GalleryAdmin` registers a consigning artist against a gallery by supplying the `gallery_id` and the artist's `full_name`, optionally with a `split_override_bps` between 0 and 10000 inclusive. When `split_override_bps` is present it overrides the gallery default for that artist; when it is absent the gallery's `default_consignment_split_bps` applies. A new artist begins with `status` of `ACTIVE` and all three ledger counters — `ledger_accrued_cents`, `ledger_paid_cents`, and `ledger_payable_cents` — at zero.

An artist's lifecycle has two transitions, both reserved to a `GalleryAdmin`. Suspending an artist requires that the artist is currently `ACTIVE` and moves them `ACTIVE → SUSPENDED`; while suspended, the artist may not consign new artworks and may not receive new payouts. Reinstating an artist requires that they are currently `SUSPENDED` and moves them `SUSPENDED → ACTIVE` with no further effect. The suspension gate is enforced at three points — consigning an artwork, creating a sale of the artist's work, and creating a payout — and each rejects with `ERR_ARTIST_SUSPENDED` when the relevant artist is `SUSPENDED`.

### 3.2. Consignment Inventory and Provenance

A `GalleryAdmin` or a `Registrar` consigns an artwork by supplying its `gallery_id`, the consigning `artist_id`, a `title`, a `list_price_cents` (the asking price, strictly greater than zero), and an `insured_value_cents` (the declared replacement value used later for loan coverage, also strictly greater than zero). If the named artist is `SUSPENDED`, the consignment is refused with `ERR_ARTIST_SUSPENDED`. A freshly consigned work enters `status` of `CONSIGNED`, and the system appends a first provenance entry recording the consignment event; this creation-time entry uses the `event` text `CONSIGNED` and is part of creation rather than a separate mutation, so a freshly consigned work reads `version` 1 and `provenance_count` 1.

Provenance is an append-only ownership history. Each artwork holds a `provenance_log`, an ordered array of records each shaped `{seq, event, at_utc}` where `seq` starts at 1 and increases by one per entry, and a `provenance_count` giving the number of entries appended. Only a `Registrar` may append a manual provenance entry, supplying the `event` text; the entry is stamped with the current clock as its `at_utc` and `provenance_count` is incremented. An append with a missing `event` field, or whose `event` is not a string, is rejected with `ERR_INVALID_REQUEST`; an append whose `event` string is present but empty or only whitespace is rejected with `ERR_DUPLICATE_PROVENANCE_EVENT`. Beyond manual appends, the system writes provenance automatically as the work moves through its life, each with a fixed `event` token: a reservation entry (`RESERVED`) when a sale reserves it, a sale-voided entry (`SALE_VOIDED`) when that sale is voided, a sold entry (`SOLD`) at settlement, a loaned-out entry (`LOANED_OUT`) when it goes on loan, a loan-returned entry (`LOAN_RETURNED`) when it comes back, a lease-returned entry (`LEASE_RETURNED`) when a lease ends by return, a shipped entry (`SHIPPED`) when a sale ships, and a returned-to-artist entry (`RETURNED_TO_ARTIST`) when the work is returned to its maker. A lease that ends by termination or by conversion writes no lease-specific provenance entry (conversion instead writes a `RESERVED` entry as it opens the buyout sale). Each automatic and manual append is a mutation that refreshes the artwork's `updated_at` and increments its `version`.

An artwork's inventory status is cyclic. From `CONSIGNED` it may move to `RESERVED` (a sale is created against it), to `ON_LOAN` (a loan is created against it), or to `RETURNED` (a `GalleryAdmin` returns the consigned work to the artist, requiring the work to be `CONSIGNED` and appending the returned-to-artist provenance entry). From `RESERVED` it can revert to `CONSIGNED` if the sale is voided, or advance to `SOLD` when the sale settles; `SOLD` is terminal. From `ON_LOAN` it returns to `CONSIGNED` when the loan is returned or the lease that put it out ends. The legal status values are `CONSIGNED`, `RESERVED`, `SOLD`, `ON_LOAN`, and `RETURNED`.

### 3.3. Exhibitions and the Wall Map

A `GalleryAdmin` schedules an exhibition by supplying its `gallery_id`, a `title`, the `wall_capacity` (the number of physical slots on the floor plan, strictly greater than zero), an `opens_utc` (the inclusive lower bound of the run window), and a `closes_utc` (the exclusive upper bound), where `closes_utc` must be strictly after `opens_utc`. A show begins `PLANNED` with `slots_occupied` at 0; its `slots_available` is always `wall_capacity` minus `slots_occupied`. The valid show states are `PLANNED`, `OPEN`, `CLOSED`, and `CANCELLED`.

From `PLANNED` an exhibition branches two ways. A `GalleryAdmin` opens it — moving `PLANNED → OPEN` — only when the show is `PLANNED`, at least one slot is occupied, and the clock has reached or passed `opens_utc`; a violation of any of these three preconditions (wrong status, zero occupied slots, or clock before `opens_utc`) is rejected with `ERR_INVALID_STATE`. Once open, further placements are still allowed up to capacity. Alternatively a `GalleryAdmin` cancels it, moving `PLANNED → CANCELLED`, which fans out: every `PLACED` wall slot on the show is set `RELEASED` and `slots_occupied` drops to 0; every `OpeningEvent` for the show still in `SCHEDULED` status is moved to `CANCELLED`; and every `CONFIRMED` or `WAITLISTED` RSVP on those events is moved to `CANCELLED`. From `OPEN`, a `GalleryAdmin` closes the show — moving `OPEN → CLOSED` — only once the clock has reached or passed `closes_utc` (a close attempt while not `OPEN`, or before the clock reaches `closes_utc`, is rejected with `ERR_INVALID_STATE`); closing releases every still-`PLACED` wall slot and drops `slots_occupied` to 0. Both `CLOSED` and `CANCELLED` are terminal.

Placing an artwork on the wall map is done by a `GalleryAdmin` or a `Registrar` against a named exhibition, supplying the `artwork_id`, a human `wall_label` such as "N-12", a `position_index` (an ordinal at least 0), and the `expected_exhibition_version` described in §2.9. A successful placement creates a `WallSlot` in `status` of `PLACED`, increments the exhibition's `version` by one, and recomputes `slots_occupied` and `slots_available`; the slot's own `gallery_id` and `exhibition_id` come from the parent show. A slot's lifecycle status is either `PLACED` or `RELEASED`. Two structural guards apply: a placement that would push the occupied count past `wall_capacity`, or that reuses a `position_index` already taken by a `PLACED` slot of the same exhibition, is rejected with `ERR_WALL_CAPACITY_EXCEEDED`.

A third guard protects the show calendar. A placement is rejected with `ERR_SCHEDULE_CONFLICT` when the same artwork is already `PLACED` in another non-terminal exhibition — one whose status is `PLANNED` or `OPEN` — whose run window intersects this show's run window. For exhibitions the overlap test is on closed intervals: two shows conflict if their `[opens_utc, closes_utc]` ranges touch at all, and sharing a single boundary instant counts as a conflict. This is stricter than the loan calendar, which treats its boundaries as half-open (see §3.7).

### 3.4. Reserving and Pricing a Sale

A `SalesAssociate` or `GalleryAdmin` opens a sale to reserve an artwork, supplying the `gallery_id`, the `artwork_id`, a `buyer_name`, a two-letter uppercase `buyer_state_code` (the ship-to state, exactly two uppercase letters), a `gross_amount_cents` (the negotiated price before discount, tax, and shipping, strictly greater than zero), and optionally the `exhibition_id` the work was placed in, a `discount_bps` (0 to 10000 inclusive, defaulting to 0), and a `shipping_cents` (at least 0, defaulting to 0). The artwork must be `CONSIGNED`; if its artist is `SUSPENDED` the sale is refused with `ERR_ARTIST_SUSPENDED`. On success the system creates the sale with `settlement_status` of `RESERVED` and `shipping_status` of `PENDING`, moves the artwork `CONSIGNED → RESERVED`, appends a reservation provenance entry, and computes both the money breakdown and the provisional artist share.

The money breakdown is computed as follows. The `net_amount_cents` is the gross amount reduced by the discount: take `gross_amount_cents`, multiply by the quantity (10000 minus `discount_bps`), divide by 10000, and round half up to whole cents — this net is the consignment-split base. Whether tax applies turns on an exemption test: the sale is **tax-exempt** if the buyer ships to a state different from the gallery's `home_state_code`, OR if the gallery's `resale_exempt_threshold_cents` is greater than 0 and the `gross_amount_cents` is strictly greater than that threshold (a wholesale or resale-certificate line; a threshold of 0 disables this second path). When the sale is exempt, `tax_amount_cents` is 0; otherwise `tax_amount_cents` is the net amount multiplied by the gallery's `sales_tax_rate_bps`, divided by 10000, rounded half up — tax is computed on the post-discount net, never on the gross. The `buyer_total_cents` is then `net_amount_cents` plus `tax_amount_cents` plus `shipping_cents`; shipping is added to what the buyer owes but is never itself taxed.

The consignment split decides how the net is divided between artist and gallery, using an effective rate of the artist's `split_override_bps` when that is set, otherwise the gallery's `default_consignment_split_bps`. The split is computed in two variants. The **provisional** variant runs at reservation: the split is applied to the net derived from the *undiscounted* gross — that is, the gross rounded half up as if no discount applied — multiplied by the effective split basis points and divided by 10000, rounded half up. This provisional figure is stored in `artist_share_cents` so the artist sees the headline cut at reservation, but it is not accrued to the ledger. The **final** variant runs at settlement: the split is applied to the realized `net_amount_cents` (post-discount), multiplied by the effective split basis points, divided by 10000, rounded half up, and this final figure replaces `artist_share_cents`. In both variants `gallery_share_cents` is `net_amount_cents` minus `artist_share_cents`. Only the final value lands in the artist's accrued ledger.

The sale also tracks `amount_collected_cents`, the sum of posted installment amounts plus any single full payment, which starts at 0. Settlement status walks the value `RESERVED`, `INVOICED`, `PARTIALLY_PAID`, `SETTLED`, and `VOID`, with `SETTLED` and `VOID` terminal.

### 3.5. Invoicing, Collecting, Settling, and Voiding

Once a buyer is committed, a `SalesAssociate` or `GalleryAdmin` invoices the sale, which requires `settlement_status` of `RESERVED` and moves it `RESERVED → INVOICED`, locking the buyer total and making the sale collectible either by a single payment or through a payment plan.

Payments are posted against an invoiced or partially paid sale. A posting requires `settlement_status` to be `INVOICED` or `PARTIALLY_PAID` and carries an `amount_cents` plus the `expected_sale_version` for the concurrency check of §2.9. The posted `amount_cents` is added to `amount_collected_cents` and the sale's `version` is incremented. A posting that would push `amount_collected_cents` strictly above `buyer_total_cents` is rejected with `ERR_OVERPAYMENT`. If the posting brings the collected amount to a value still below the buyer total, the sale moves to `PARTIALLY_PAID`. When a payment plan is attached to the sale, each accepted posting also advances the plan's `posted_installment_count`, and when that count reaches the plan's `installment_count` the plan auto-completes (see §3.6).

Settling closes the money side. A `SalesAssociate` or `GalleryAdmin` settles a sale only when `settlement_status` is `INVOICED` or `PARTIALLY_PAID` and `amount_collected_cents` exactly equals `buyer_total_cents`; the sale then moves to `SETTLED`. Settlement recomputes `artist_share_cents` with the final split variant, drives the artwork `RESERVED → SOLD`, releases every wall slot the work still holds — every `PLACED` `WallSlot` whose `artwork_id` is this artwork, across any exhibition, is set to `RELEASED` and the affected exhibitions' slot counts recompute on their next read — appends a sold provenance entry, and fires the ledger accrual: the artist's `ledger_accrued_cents` increases by the final `artist_share_cents` and `ledger_payable_cents` is recomputed. This is the single point at which artist money becomes real.

Voiding is the compensating path. A `SalesAssociate` or `GalleryAdmin` may void a sale whose `settlement_status` is `RESERVED`, `INVOICED`, or `PARTIALLY_PAID` — never one already `SETTLED` — moving it to `VOID`. Voiding reverts the artwork `RESERVED → CONSIGNED`, appends a sale-voided provenance entry, cancels any `ACTIVE` payment plan on the sale (moving it to `CANCELLED`), and releases every `PLACED` `WallSlot` whose `artwork_id` is this artwork — across any exhibition, not only the sale's own `exhibition_id` — to `RELEASED`, with the affected exhibitions' slot counts recomputing on their next read.

A sale's fulfilment dimension runs independently of its money dimension. The `shipping_status` value is `PENDING`, `SHIPPED`, or `DELIVERED`, with `DELIVERED` terminal. A `SalesAssociate` or `GalleryAdmin` ships a sale — moving `PENDING → SHIPPED` and appending a shipped provenance entry to the artwork — only when `shipping_status` is `PENDING` and the sale's `settlement_status` is not `VOID`; both conditions surface as `ERR_INVALID_STATE`, with the `shipping_status` check evaluated before the not-`VOID` check. Delivery moves `SHIPPED → DELIVERED` and requires the sale to be `SHIPPED`. Because the two dimensions are independent, a sale may ship before or after it is settled.

### 3.6. Payment Plans and Default

A `SalesAssociate` or `GalleryAdmin` attaches an installment plan to a sale by supplying the `sale_id`, an `installment_count` (at least 2 and at most 24), a `cadence_days` (at least 1), and a `first_due_utc` (the due instant of the first installment). The linked sale must be in `INVOICED` state; a plan created against a sale not in that state is rejected with `ERR_PLAN_SALE_NOT_INVOICED`. A new plan starts `ACTIVE`; the legal plan states are `ACTIVE`, `COMPLETED`, `DEFAULTED`, and `CANCELLED`.

The schedule is computed from the linked sale's `buyer_total_cents`. The base per-installment amount, `installment_cents`, is the buyer total divided by `installment_count` discarding any fractional cent (floor division). The remainder — the buyer total minus `installment_cents` multiplied by `installment_count` — is loaded entirely onto the last installment, so `final_installment_cents` equals `installment_cents` plus that remainder. Installments 1 through the second-to-last each equal `installment_cents`; only the final installment carries the remainder, which is never spread across the earlier ones.

Two derived counters track progress against the clock. `posted_installment_count` is how many installments have been posted so far. To find what is overdue, the system determines which installments are **due**: installment number `k` is due once the clock has reached or passed `first_due_utc` plus `(k − 1)` times `cadence_days` (each cadence day being 86,400 seconds), and the boundary is inclusive — the instant a due time arrives, that installment counts as due. The `missed_installment_count` is the number of due installments minus the number posted, floored at zero.

A plan reaches `DEFAULTED` only through an explicit sweep by a `SalesAssociate` or `GalleryAdmin`: the sweep requires the plan to be `ACTIVE` and moves it `ACTIVE → DEFAULTED` when `missed_installment_count` is at least 2; below that the sweep is a no-op. (Two is the missed-installment ceiling — a plan tolerates at most one missed installment before a sweep can default it.) A defaulted plan does not settle its sale and produces no artist accrual. Separately, a plan auto-completes — `ACTIVE → COMPLETED`, performed by the system — on the payment that brings `posted_installment_count` equal to `installment_count`, after which the linked sale is eligible to settle. And when the linked sale is voided, the system moves any `ACTIVE` plan `ACTIVE → CANCELLED`.

### 3.7. Loans, Insurance Coverage, and the Booking Calendar

A `Registrar` or `GalleryAdmin` loans an artwork out by supplying the `artwork_id`, a `borrower_name`, a `coverage_value_cents` (the insurance the borrower has secured, strictly greater than zero), an `out_utc` (the inclusive instant the work leaves), and a `due_utc` (the exclusive scheduled-return instant, which must be strictly after `out_utc`). The artwork must be `CONSIGNED`. Two business guards apply. Coverage adequacy is checked first: the borrower's `coverage_value_cents` must be at least the artwork's `insured_value_cents`; equal coverage passes, and strictly-less coverage is rejected with `ERR_INSUFFICIENT_COVERAGE`. The schedule guard is checked against the artwork's full loan history: the new loan's window, treated as the half-open interval from `out_utc` up to but not including `due_utc`, must not overlap the window of any prior loan ever recorded for the same artwork — regardless of whether that earlier loan is `OUTSTANDING`, `OVERDUE`, or already `RETURNED` — and an overlap is rejected with `ERR_SCHEDULE_CONFLICT`. Because the windows are half-open, two loans that merely abut at a shared boundary instant do not conflict, which is the opposite of the closed-interval rule for exhibitions in §3.3.

A successful loan is created `OUTSTANDING`, drives the artwork `CONSIGNED → ON_LOAN`, and appends a loaned-out provenance entry; its `returned_utc` is null until return. The legal loan states are `OUTSTANDING`, `RETURNED`, and `OVERDUE`, with `RETURNED` terminal. A `Registrar` or `GalleryAdmin` returns a loan — permitted while it is `OUTSTANDING` or `OVERDUE` — setting `status` to `RETURNED`, stamping `returned_utc` with the current clock, driving the artwork `ON_LOAN → CONSIGNED`, and appending a loan-returned provenance entry. Separately, a `Registrar` or `GalleryAdmin` sweeps an outstanding loan for overdue status: the sweep requires the loan to be `OUTSTANDING` and the clock to have reached or passed `due_utc` (a sweep on a non-`OUTSTANDING` loan or before the clock reaches `due_utc` is rejected with `ERR_INVALID_STATE`), and it flags the loan `OUTSTANDING → OVERDUE` for reporting while the artwork stays `ON_LOAN`.

### 3.8. Art Leases and Buyout Conversion

A `SalesAssociate` or `GalleryAdmin` writes an art-lease agreement against an artwork by supplying the `artwork_id`, a `lessee_name`, a `monthly_rate_cents` (strictly greater than zero), a `term_months` (at least 1), a `starts_utc`, and optionally a `purchase_credit_bps` (0 to 10000 inclusive, defaulting to 0) giving the fraction of paid rent credited toward a buyout. Creating a lease puts the artwork `CONSIGNED → ON_LOAN` and starts the agreement `ACTIVE`; the legal lease states are `ACTIVE`, `CONVERTED`, `RETURNED`, and `TERMINATED`.

Three derived figures track the lease against the clock. The `months_accrued` is the whole months elapsed since `starts_utc`, computed by taking the time since the start, dividing into 30-day blocks and discarding the fraction, then capping the result at `term_months`. The `rent_accrued_cents` is `months_accrued` multiplied by `monthly_rate_cents`. The `buyout_price_cents` is the artwork's `list_price_cents` minus the credited rent, where the credited rent is `rent_accrued_cents` multiplied by `purchase_credit_bps` divided by 10000 and rounded half up; the buyout is floored at zero and never goes negative.

A lease ends one of three ways while it is `ACTIVE`. Converting it — by a `SalesAssociate` or `GalleryAdmin` — moves it `ACTIVE → CONVERTED` and requires the leased artwork to be `ON_LOAN` under the lease; a convert attempted when the artwork is not out under the lease is rejected with `ERR_LEASE_ARTWORK_NOT_OUT`. Conversion creates a sale against the artwork at a `gross_amount_cents` equal to the current `buyout_price_cents` with `settlement_status` of `RESERVED`, and drives the artwork `ON_LOAN → RESERVED`. The generated sale takes the lease's `lessee_name` as its `buyer_name`, the gallery's `home_state_code` as its `buyer_state_code`, a `discount_bps` of 0, a `shipping_cents` of 0, and no `exhibition_id`; its money breakdown and provisional artist share are computed exactly as for a normal reservation, and a `RESERVED` provenance entry is appended to the artwork. The convert endpoint returns the updated lease resource (now `CONVERTED`), not the newly created sale, in its `data`. Returning the lease — by a `SalesAssociate` or `GalleryAdmin` — moves it `ACTIVE → RETURNED`, drives the artwork `ON_LOAN → CONSIGNED`, and appends a lease-returned provenance entry. Terminating the lease — reserved to a `GalleryAdmin`, for cause — moves it `ACTIVE → TERMINATED` and drives the artwork `ON_LOAN → CONSIGNED`.

### 3.9. Opening Receptions and Seat Allocation

A `GalleryAdmin` creates an opening reception for an exhibition by supplying the `exhibition_id`, a `capacity` (the maximum confirmed guests, strictly greater than zero), a `starts_utc`, and an `rsvp_deadline_utc` (the latest instant an RSVP may be confirmed, which must be at or before `starts_utc`). The event begins `SCHEDULED` with `confirmed_count` and `waitlist_count` at 0; the legal event states are `SCHEDULED`, `CLOSED`, and `CANCELLED`. The live `confirmed_count` is the number of RSVPs in either `CONFIRMED` or `PROMOTED` status for the event (a head count of rows, not a party-size-weighted seat total) and `waitlist_count` the number in `WAITLISTED` status.

Guests RSVP through a `GalleryAdmin` or `SalesAssociate`, supplying the `opening_event_id`, a `guest_name`, and optionally a `party_size` (at least 1 and at most 10, defaulting to 1) giving how many seats the RSVP consumes. Capacity is party-size-weighted: the confirmed seat count is the sum of `party_size` over all RSVPs that are `CONFIRMED` or `PROMOTED` on the event. A new RSVP is persisted directly as `CONFIRMED` when the confirmed seat count plus this RSVP's `party_size` is less than or equal to `capacity`; otherwise it is persisted directly as `WAITLISTED` (incrementing `waitlist_count`) — being waitlisted is a normal outcome, not an error. The `party_size` value itself must be an integer in 1..10, checked at body well-formedness and rejected with `ERR_INVALID_REQUEST`. An RSVP may only be created while the clock is at or before the event's `rsvp_deadline_utc`; a create after the deadline, or on a `CLOSED` or `CANCELLED` event, is rejected with `ERR_RSVP_CLOSED`. The `party_size` must itself be no greater than `capacity`; a request for more seats than the event can ever hold is rejected with `ERR_INVALID_REQUEST` — but this `party_size > capacity` check is evaluated only after the deadline/event-state guard, so a too-large party on a closed or past-deadline event returns `ERR_RSVP_CLOSED` rather than `ERR_INVALID_REQUEST`. RSVP statuses are `CONFIRMED`, `WAITLISTED`, `CANCELLED`, and `PROMOTED`, with `CANCELLED` and `PROMOTED` terminal.

Cancelling an RSVP is done by a `GalleryAdmin` or `SalesAssociate`. Cancelling a `CONFIRMED` RSVP requires the event to still be `SCHEDULED`, moves the RSVP to `CANCELLED`, and frees its seats — at which point the system promotes from the waitlist: it walks the `WAITLISTED` RSVPs in `created_at` ascending order, and for each one promotes it to `PROMOTED` only if its `party_size` fits within the seats now free, stopping at the first RSVP that does not fit without skipping ahead to a smaller one. Each promotion makes those seats count as confirmed seating again, and `confirmed_count` is recomputed to include `PROMOTED` rows. Cancelling a `WAITLISTED` RSVP simply moves it to `CANCELLED` with no promotion cascade.

An event closes or cancels through a `GalleryAdmin`. Closing requires the event to be `SCHEDULED` and moves it `SCHEDULED → CLOSED`, after which no further RSVPs are accepted; waitlisted RSVPs are deliberately not auto-promoted on close. Cancelling requires the event to be `SCHEDULED`, moves it `SCHEDULED → CANCELLED` (and the system also performs this when the parent exhibition is cancelled), and moves every `CONFIRMED` or `WAITLISTED` RSVP on the event to `CANCELLED`.

### 3.10. Artist Payouts and Reporting

Once an artist has accrued a payable balance, a `GalleryAdmin` creates a payout by supplying the `artist_id` and a `requested_cents` (the amount the operator asks to disburse, strictly greater than zero). The payout is refused with `ERR_ARTIST_SUSPENDED` if the artist is `SUSPENDED`, and with `ERR_NO_PAYABLE_BALANCE` if the artist's `ledger_payable_cents` is 0 at creation. On success the payout is created `PENDING`, and its `approved_cents` — the amount actually swept — is set to the smaller of `requested_cents` and the artist's `ledger_payable_cents` at the moment of creation; the create response already carries this `approved_cents`. The legal payout states are `PENDING`, `COMPLETED`, and `REVERSED`, with `REVERSED` terminal.

A `GalleryAdmin` completes a payout — moving `PENDING → COMPLETED` — which increases the artist's `ledger_paid_cents` by `approved_cents` and recomputes `ledger_payable_cents`. The compensating action is reversal: a `GalleryAdmin` reverses a `COMPLETED` payout, moving it `COMPLETED → REVERSED`, which decreases the artist's `ledger_paid_cents` by `approved_cents` and recomputes `ledger_payable_cents`, returning the paid figure to its pre-completion value. The conservation invariant of §2.10 holds across all three steps.

For oversight, a `GalleryAdmin` may pull a sales-summary report over a window bounded by an optional `from_utc` and an optional `to_utc` (each, when supplied, must be a valid ISO 8601 instant or the request is rejected with `ERR_INVALID_REQUEST`). A sale falls in the window by comparing its `updated_at` record stamp (which last moved at settlement) against the bounds: a sale is excluded when its `updated_at` is strictly before `from_utc` or strictly after `to_utc`, so both bounds are inclusive and an omitted bound is unbounded on that side. The report aggregates over settled sales in the window and returns the count of settled sales as `settled_sale_count`, along with `gross_total_cents`, `net_total_cents`, `tax_total_cents`, `shipping_total_cents`, `artist_share_total_cents`, and `gallery_share_total_cents` — the running totals of each corresponding per-sale figure across those settled sales.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify an existing resource, drive a state transition, or read return `200 OK`. The request and response payloads for each endpoint are not restated here — they are described in the §3 workflows above; this table is a routing and authorization summary only.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the logical clock to a UTC instant | GalleryAdmin |
| POST | `/galleries` | Create a gallery | GalleryAdmin |
| GET | `/galleries/{gallery_id}` | Get a gallery | GalleryAdmin, Registrar, SalesAssociate, Artist |
| POST | `/artists` | Register a consigning artist | GalleryAdmin |
| GET | `/artists` | List artists (filterable) | GalleryAdmin, Registrar, SalesAssociate, Artist |
| GET | `/artists/{artist_id}` | Get an artist with live ledger fields | GalleryAdmin, Registrar, SalesAssociate, Artist |
| POST | `/artists/{artist_id}/suspend` | Suspend an artist | GalleryAdmin |
| POST | `/artists/{artist_id}/reinstate` | Reinstate a suspended artist | GalleryAdmin |
| POST | `/artworks` | Consign an artwork | GalleryAdmin, Registrar |
| GET | `/artworks` | List artworks (filterable) | GalleryAdmin, Registrar, SalesAssociate, Artist |
| GET | `/artworks/{artwork_id}` | Get an artwork including provenance | GalleryAdmin, Registrar, SalesAssociate, Artist |
| POST | `/artworks/{artwork_id}/provenance` | Append a provenance entry | Registrar |
| POST | `/artworks/{artwork_id}/return-to-artist` | Return a consigned artwork to the artist | GalleryAdmin |
| POST | `/exhibitions` | Schedule an exhibition | GalleryAdmin |
| GET | `/exhibitions` | List exhibitions (filterable) | GalleryAdmin, Registrar, SalesAssociate, Artist |
| GET | `/exhibitions/{exhibition_id}` | Get an exhibition with live slot counts | GalleryAdmin, Registrar, SalesAssociate, Artist |
| POST | `/exhibitions/{exhibition_id}/wall-slots` | Place an artwork on the wall map | GalleryAdmin, Registrar |
| GET | `/exhibitions/{exhibition_id}/wall-slots` | List wall slots of an exhibition | GalleryAdmin, Registrar, SalesAssociate, Artist |
| GET | `/wall-slots` | List wall slots (filterable) | GalleryAdmin, Registrar, SalesAssociate, Artist |
| GET | `/wall-slots/{wall_slot_id}` | Get a single wall slot | GalleryAdmin, Registrar, SalesAssociate, Artist |
| POST | `/exhibitions/{exhibition_id}/open` | Open an exhibition | GalleryAdmin |
| POST | `/exhibitions/{exhibition_id}/close` | Close an exhibition | GalleryAdmin |
| POST | `/exhibitions/{exhibition_id}/cancel` | Cancel a planned exhibition | GalleryAdmin |
| POST | `/sales` | Create a sale (reserve an artwork) | SalesAssociate, GalleryAdmin |
| GET | `/sales` | List sales (filterable) | GalleryAdmin, SalesAssociate, Artist |
| GET | `/sales/{sale_id}` | Get a sale with full money breakdown | GalleryAdmin, SalesAssociate, Artist |
| POST | `/sales/{sale_id}/invoice` | Invoice a reserved sale | SalesAssociate, GalleryAdmin |
| POST | `/sales/{sale_id}/payments` | Post a payment / installment | SalesAssociate, GalleryAdmin |
| POST | `/sales/{sale_id}/settle` | Settle a fully-paid sale | SalesAssociate, GalleryAdmin |
| POST | `/sales/{sale_id}/void` | Void a non-settled sale | SalesAssociate, GalleryAdmin |
| POST | `/sales/{sale_id}/ship` | Mark a sale shipped | SalesAssociate, GalleryAdmin |
| POST | `/sales/{sale_id}/deliver` | Mark a sale delivered | SalesAssociate, GalleryAdmin |
| POST | `/payment-plans` | Create an installment plan for an invoiced sale | SalesAssociate, GalleryAdmin |
| GET | `/payment-plans` | List payment plans (filterable) | GalleryAdmin, SalesAssociate |
| GET | `/payment-plans/{plan_id}` | Get a plan with live missed/posted counts | GalleryAdmin, SalesAssociate |
| POST | `/payment-plans/{plan_id}/sweep-overdue` | Evaluate a plan and default it if overdue | SalesAssociate, GalleryAdmin |
| POST | `/leases` | Create an art-lease agreement | SalesAssociate, GalleryAdmin |
| GET | `/leases` | List leases (filterable) | GalleryAdmin, SalesAssociate, Registrar |
| GET | `/leases/{lease_id}` | Get a lease with live accrual and buyout | GalleryAdmin, SalesAssociate, Registrar |
| POST | `/leases/{lease_id}/convert` | Convert a lease into a purchase | SalesAssociate, GalleryAdmin |
| POST | `/leases/{lease_id}/return` | Return a leased artwork | SalesAssociate, GalleryAdmin |
| POST | `/leases/{lease_id}/terminate` | Terminate a lease for cause | GalleryAdmin |
| POST | `/opening-events` | Create an opening reception | GalleryAdmin |
| GET | `/opening-events` | List opening events (filterable) | GalleryAdmin, SalesAssociate, Registrar, Artist |
| GET | `/opening-events/{event_id}` | Get an opening event with live counts | GalleryAdmin, SalesAssociate, Registrar, Artist |
| POST | `/opening-events/{event_id}/close` | Close RSVPs for an event | GalleryAdmin |
| POST | `/opening-events/{event_id}/cancel` | Cancel an event | GalleryAdmin |
| POST | `/rsvps` | Create an RSVP | GalleryAdmin, SalesAssociate |
| GET | `/rsvps` | List RSVPs (filterable) | GalleryAdmin, SalesAssociate, Registrar |
| GET | `/rsvps/{rsvp_id}` | Get a single RSVP | GalleryAdmin, SalesAssociate, Registrar |
| POST | `/rsvps/{rsvp_id}/cancel` | Cancel an RSVP | GalleryAdmin, SalesAssociate |
| POST | `/loans` | Loan an artwork out | Registrar, GalleryAdmin |
| GET | `/loans` | List loans (filterable) | GalleryAdmin, Registrar |
| GET | `/loans/{loan_id}` | Get a loan | GalleryAdmin, Registrar |
| POST | `/loans/{loan_id}/return` | Return a loaned artwork | Registrar, GalleryAdmin |
| POST | `/loans/{loan_id}/sweep-overdue` | Flag an outstanding loan overdue | Registrar, GalleryAdmin |
| POST | `/payouts` | Create a payout for an artist | GalleryAdmin |
| GET | `/payouts` | List payouts (filterable) | GalleryAdmin, Artist |
| GET | `/payouts/{payout_id}` | Get a payout | GalleryAdmin, Artist |
| POST | `/payouts/{payout_id}/complete` | Mark a payout completed | GalleryAdmin |
| POST | `/payouts/{payout_id}/reverse` | Reverse a completed payout | GalleryAdmin |
| GET | `/reports/sales-summary` | Computed sales-summary report over settled sales | GalleryAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_ARTIST_SUSPENDED` | 409 |
| `ERR_INSUFFICIENT_COVERAGE` | 409 |
| `ERR_SCHEDULE_CONFLICT` | 409 |
| `ERR_WALL_CAPACITY_EXCEEDED` | 409 |
| `ERR_RSVP_CLOSED` | 409 |
| `ERR_OVERPAYMENT` | 409 |
| `ERR_NO_PAYABLE_BALANCE` | 409 |
| `ERR_PLAN_SALE_NOT_INVOICED` | 409 |
| `ERR_LEASE_ARTWORK_NOT_OUT` | 409 |
| `ERR_VALIDATION_PAGINATION` | 400 |
| `ERR_DUPLICATE_PROVENANCE_EVENT` | 409 |
