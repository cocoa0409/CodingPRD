# Municipal Cemetery Management API — Product Requirements Document

## 1. Introduction

Municipal cemeteries sit at an unusual intersection of land management, public health law, family bereavement, and long-horizon fiduciary duty. A single grave is simultaneously a parcel of surveyed real estate, the subject of a legally conveyed right of interment, the resting place of one or more decedents, and the beneficiary of a perpetual-care endowment that must outlive everyone who ever touched the record. The Municipal Cemetery Management API is the system of record that keeps these concerns coherent: it tracks plot and grave inventory together with its GIS coordinates, sells and transfers deeds (rights of interment), schedules the opening and closing crews, administers the perpetual-care fund as an append-only ledger, answers genealogy and records lookups, issues foundation and marker permits, authorizes disinterments under strict consent and segregation controls, and bills every one of these events.

This document specifies the API that municipal records offices, grounds crews, finance departments, and public-health officers use to run day-to-day cemetery operations. The domain is compliance-heavy: most state actions are gated on prior approvals, paid invoices, and separation of the person who approves an action from the person who carries it out. It is also temporally sensitive — graves cannot be opened before their scheduled date, crews cannot be double-booked, and short-notice services carry surcharges — so the server runs on a controllable logical clock rather than wall-clock time. The reader should treat every threshold, every state precondition, and every cascade described below as load-bearing; the workflows are deliberately interdependent, and correctness depends on honoring them exactly.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API. Every endpoint is mounted under the `/cemetery-mgmt` path prefix.

### 2.1. User and Role-Based Access Control

All interactions with the API must be authenticated through a pair of mandatory HTTP headers. Each request must include `X-User-ID` to identify the acting user and `X-User-Role` to declare their operational capacity. When the `X-User-Role` header is missing or does not name one of the recognized roles, the request is rejected with `ERR_UNAUTHENTICATED`. When the role is recognized but is not permitted to perform the requested operation — or, for an entity-backed role, does not own the target resource — the request is rejected with `ERR_FORBIDDEN`.

The system recognizes exactly six roles: `Registrar`, `GroundsForeman`, `FinanceOfficer`, `HealthOfficer`, `CemeteryDirector`, and `RightHolder`.

- The `Registrar` staffs the records office: they create plots, holders, and decedent records; sell, transfer, and surrender deeds; schedule and cancel interments; and request and execute disinterments.
- The `GroundsForeman` is the field crew: they open and close (complete) graves and record marker installations.
- The `FinanceOfficer` owns billing: recording payments, voiding invoices under maker-checker control, and posting perpetual-care ledger entries.
- The `HealthOfficer` is the public-health authority and records disinterment clearance.
- The `CemeteryDirector` is the approving authority: they create cemeteries, retire plots, and approve or deny marker permits and disinterment authorizations.
- The `RightHolder` is the holder of an interment right, acting on their own resources.

Five of these roles carry an **opaque** identity. When `X-User-Role` is `Registrar`, `GroundsForeman`, `FinanceOfficer`, `HealthOfficer`, or `CemeteryDirector`, the `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it (for example as `approved_by_user_id` on a disinterment authorization, or as `issued_by_user_id` on an invoice) but never compares it to any entity's `id`. The `RightHolder` role is **entity-backed**: when `X-User-Role` is `RightHolder`, the `X-User-ID` is the `id` of the acting `RightHolder`, and ownership checks on any resource that references a `RightHolder` compare that resource's holder foreign key to `X-User-ID`. In particular, only the proposed recipient of a pending deed transfer may accept it, and only the holder tied to an interment's deed may record next-of-kin consent for its disinterment.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; when omitted it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter is the number of items to skip and defaults to 0. Unless a specific endpoint states otherwise, all list endpoints return resources sorted by their `created_at` timestamp in ascending order. Every list response includes `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope.

### 2.4. Common Resource Properties, Versioning, and Optimistic Concurrency

Most primary resources — `Cemetery`, `Plot`, `RightHolder`, `Deed`, `Interment`, `DisintermentAuthorization`, `MarkerPermit`, and `Invoice` — carry a standard set of system-managed fields. Each has an `id` that is a server-minted UUID with no type prefix, a `created_at` and an `updated_at` that are ISO 8601 UTC timestamps with three fractional digits, and an integer `version`. The `version` starts at 1 on creation and increments by one on every mutation; `updated_at` is refreshed on every mutation to mirror the most recent change.

Three record types are deliberately lighter. A `Decedent` is an immutable genealogy record and a `Payment` and a `CareFundEntry` are append-only events; each of these carries only `id` and `created_at`. They have no `updated_at` and no `version` at all, and once written they are never modified in place.

**Optimistic concurrency on plot sales.** Selling a right of interment is the one write in this system guarded by optimistic concurrency control. A request to create a `Deed` must carry `expected_plot_version` as a non-optional field whose value is the `version` of the target `Plot` that the client last observed. Before reserving the plot, the server compares `expected_plot_version` against the plot's current `version`; if another writer has advanced the plot's version since the client last read it — for example by already creating a deed that legitimately reserves the plot — the create is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the client from acting on a stale view of the plot. No other endpoint accepts or requires a version field; only deed creation is version-checked.

### 2.5. Validation Ordering and Nested Path Resolution

Every write is evaluated against a fixed ladder of checks, and the **first** failing rung determines the error returned. The ordering, from highest priority to lowest, is:

1. **Authentication** — the `X-User-Role` header must be present and name a recognized role, else `ERR_UNAUTHENTICATED` (401).
2. **Authorization** — the role must be permitted for the operation, and for the entity-backed `RightHolder` the acting user must own the target resource, else `ERR_FORBIDDEN` (403).
3. **Body validation** — required fields present, enum values in range, numeric fields non-negative or strictly positive as noted, and `scheduled_end` strictly after `scheduled_start`, else `ERR_VALIDATION` (400).
4. **Existence** — path identifiers and referenced foreign keys must resolve, checked left to right, else `ERR_NOT_FOUND` (404).
5. **Concurrency** — where applicable, `expected_plot_version` must equal the current `Plot.version`, else `ERR_STALE_VERSION` (412).
6. **State** — the target resource must be in a state that permits the transition, else `ERR_INVALID_STATE` (409).
7. **Cross-entity referential gates** — e.g., an `ISSUED` deed for interment scheduling and marker approval, a `COMPLETED` interment for a disinterment request, and a valid new holder for a transfer, else `ERR_DEED_NOT_ISSUED` (409) and its siblings.
8. **Consent, clearance, and segregation-of-duties gates** on disinterment approval and execution, else `ERR_CONSENT_INCOMPLETE` (409) and its siblings.
9. **Temporal gates** — a scheduled date not in the past, and grave opening only on or after the scheduled date, else `ERR_DATE_IN_PAST` (422) or `ERR_TOO_EARLY_TO_OPEN` (422).
10. **Capacity and scheduling constraints** on interment creation — plot capacity, single-booking per day, and crew-window availability, else `ERR_PLOT_CAPACITY` (409) and its siblings.
11. **Fiscal gates** — required invoices paid, payment amounts matched, and the care fund kept non-negative, else `ERR_INVOICE_UNPAID` (409) and its siblings.

For any request whose path names more than one resource, existence is validated in strict left-to-right order, and the response reports the first identifier in the path that does not resolve. A request against a child of a non-existent parent fails on the parent before the child is ever consulted.

### 2.6. Monetary Precision, Taxation, and Invoice Composition

Every monetary amount in the system is an integer number of cents. Percentage-based computations are performed with decimal arithmetic and rounded half-up to a whole cent. Wherever a rule says "rounded," it means the half-up convention applied to cents.

Every billable event produces an `Invoice`. An invoice carries a `holder_id` (the party billed), a `subject_type` and `subject_id` that together form a polymorphic reference to the entity being billed, an ordered `lines` array of line items, and three computed money fields. Each line in `lines` is an object with a `label`, an `amount_cents`, and a `taxable` boolean. The `subtotal_cents` is the sum of every line's `amount_cents`. The `tax_cents` is computed with a **pinned round-then-sum order**: for each taxable line, multiply its `amount_cents` by the tax rate of 7.25% (0.0725) and round that product half-up to a whole cent, then sum those per-line rounded amounts; non-taxable lines contribute nothing to tax. The `total_cents` is `subtotal_cents` plus `tax_cents`. Because rounding happens per line before summing, an invoice composed of several small taxable lines can total a cent differently from one taxable line of the same subtotal — this is intentional and must be preserved.

The line breakdown for each `subject_type` is fixed so totals are deterministic:

- A **DEED_SALE** invoice has two lines: a taxable `purchase_price` line for `purchase_price_cents`, followed by a non-taxable `perpetual_care` line for `care_fund_contribution_cents`. The perpetual-care contribution is never taxed.
- An **INTERMENT_SERVICE** invoice has one taxable line per **non-zero** component of the service fee, emitted in the fixed order base, then depth surcharge, then day surcharge, then short-notice surcharge. Components that evaluate to zero are omitted entirely, so tax is rounded per surviving component and then summed.
- A **MARKER_FOUNDATION** invoice has a single taxable `foundation` line for `foundation_fee_cents`.
- A **DISINTERMENT** invoice has a single taxable `disinterment` line for the flat disinterment fee.

Every invoice also records `issued_by_user_id` — the `X-User-ID` of the actor whose action generated it — and a `status` of `ISSUED`, `PAID`, or `VOID`.

### 2.7. The Perpetual-Care Fund Ledger

The perpetual-care fund is an append-only ledger scoped to a `Cemetery`. Each `CareFundEntry` names its `cemetery_id`, an `entry_type` of `CONTRIBUTION`, `DISBURSEMENT`, or `INTEREST`, a non-negative `amount_cents` magnitude whose sign is supplied by the entry type, an optional `source_deed_id` linking the entry to the deed that originated it (nullable for `INTEREST`), and an optional free-text `note`. Entries are never edited or deleted.

A cemetery's `perpetual_care_fund_balance_cents` is a computed field: it is the sum of `amount_cents` across all `CONTRIBUTION` and `INTEREST` entries for that cemetery, minus the sum of `amount_cents` across all `DISBURSEMENT` entries for that cemetery. There is no status filter — every posted entry counts. A newly created cemetery begins with a balance of zero. Any `DISBURSEMENT` that would drive the running balance below zero is rejected with `ERR_CARE_FUND_INSUFFICIENT`; the fund may reach exactly zero but never go negative.

### 2.8. Segregation of Duties and the Logical Clock

Two operations enforce **segregation of duties** (maker-checker): the same person may not both propose and finalize a sensitive action. When a `CemeteryDirector` approves a disinterment, the server records their `X-User-ID` as `approved_by_user_id`; the later execution of that disinterment is rejected with `ERR_SEGREGATION_OF_DUTIES` if the executing `Registrar`'s `X-User-ID` equals the recorded `approved_by_user_id`. Likewise, voiding an invoice is rejected with `ERR_SEGREGATION_OF_DUTIES` when the acting `FinanceOfficer`'s `X-User-ID` equals the invoice's `issued_by_user_id` — a person may not void an invoice their own action generated.

The server keeps time on a **logical clock**, never on wall-clock time. Its startup default is `2026-05-01T00:00:00Z`, used until it is explicitly set, and it never falls back to real time. An administrative test-driving capability advances the clock to a supplied `to_iso8601` instant; all temporal rules — whether a scheduled date is in the past, whether a grave may be opened yet, whether a service qualifies as short-notice, and which calendar date "today" is — are evaluated against this logical clock.

### 2.9. Cascading Consistency

Many actions in this system mutate more than one resource. Whenever a rule below says an operation "also" changes another entity, that secondary change is part of the same atomic operation: the dependent resource's own `updated_at` is refreshed and, where it carries a `version`, that `version` increments. The occupancy of a plot, the state of its deed and markers, the billing axis of an interment, and the balance of the perpetual-care fund are all kept consistent through these cascades rather than requiring separate client calls. The specific cascades — plot reclamation on deed surrender, interment retirement on disinterment execution, marker cancellation and decommissioning, and care-fund reversals — are described in §3 alongside the workflows that trigger them.

## 3. Business Logic & Workflows

### 3.1. Plots, Sections, and the GIS Inventory

A `CemeteryDirector` establishes a `Cemetery` by supplying a `name`; they may optionally supply a `timezone` (an informational IANA label defaulting to `UTC`) and a `crew_team_count`, the number of independent grounds crews available on any given day, which defaults to 1 and must be at least 1. The `crew_team_count` governs how many overlapping crew time windows the cemetery can service simultaneously, as described in the interment-scheduling rules.

A `Registrar` lays out inventory by creating a `Plot` within a cemetery. A plot references its owning cemetery through `cemetery_id` and is described by its GIS section label `section_code`, its `row` label, its `plot_number` within that row, and the latitude and longitude of its centroid in `gis_lat` and `gis_lng`. Its `plot_type` is one of `GRAVE`, `LAWN_CRYPT`, `NICHE`, or `MAUSOLEUM`, and its `interment_capacity` — the maximum number of active interments it may hold — must be at least 1. On creation a plot's `status` is `AVAILABLE` and its computed `interments_used` is 0.

A plot's `status` moves through `AVAILABLE`, `RESERVED`, `SOLD`, and the terminal `RETIRED`. The `interments_used` field is always the count of interments on the plot whose `operational_status` is `SCHEDULED`, `OPENED`, or `COMPLETED`; it is maintained so that scheduling an interment and later cancelling or disinterring it restores the prior count exactly. A `CemeteryDirector` may retire a plot, moving `AVAILABLE` to `RETIRED` and incrementing the plot's `version`; retirement is permitted only when the plot is `AVAILABLE` (otherwise `ERR_PLOT_NOT_AVAILABLE`) and its `interments_used` is exactly 0. Retirement is terminal.

Plots can be searched with the plot list, which supports filtering by `cemetery_id`, `status`, and `section_code`. Individual plots and cemeteries are retrievable by id; a cemetery read includes its live fund balance.

### 3.2. Selling and Conveying the Right of Interment

Before a deed can be sold, the buyer must exist as a `RightHolder`, created by a `Registrar` with a `full_name`, an `email`, and an optional `phone`. Genealogy records are captured as `Decedent` records, also created by a `Registrar`, carrying a `full_name`, a `date_of_death` (an ISO `YYYY-MM-DD` string), an optional `date_of_birth`, and an optional `sex` of `M`, `F`, `X`, or `UNKNOWN`. On creation the server parses `death_year` from `date_of_death`; this year is the filter key for genealogy lookup, which searches decedents by `full_name` and `death_year`. Decedent records are immutable once written.

**Creating a deed.** A `Registrar` sells a right of interment by creating a `Deed` that names the `plot_id` being conveyed, the `holder_id` acquiring the right, a `purchase_price_cents` (at least 0), and a `sale_type` of either `NEW_SALE` or `RESALE`, together with the `expected_plot_version` described in §2.4. The target plot must be `AVAILABLE`, otherwise the sale is rejected with `ERR_PLOT_NOT_AVAILABLE`. On success the deed is created in `PENDING_PAYMENT`, the plot transitions from `AVAILABLE` to `RESERVED` and its `version` increments, the deed's `care_fund_contribution_cents` is computed and pinned onto the deed, and a `DEED_SALE` invoice is issued with its identifier stored on the deed as `sale_invoice_id`.

The perpetual-care contribution depends on the sale variant. For a `NEW_SALE`, the contribution is the greater of the purchase price multiplied by 15% (0.15) and rounded half-up, or a statutory floor of 25,000 cents ($250.00) — whichever is larger. For a `RESALE`, the contribution is the purchase price multiplied by 10% (0.10) and rounded half-up, with no statutory floor. Because the two variants use different rates and only the new-sale path carries a floor, the same purchase price yields a different contribution depending on `sale_type`.

**Payment and issuance.** A deed's `status` progresses `PENDING_PAYMENT` → `ISSUED` when the `DEED_SALE` invoice is paid (see §3.7). At that moment the plot transitions from `RESERVED` to `SOLD` and its `version` increments, and a `CONTRIBUTION` care-fund entry equal to the deed's pinned `care_fund_contribution_cents` is posted with its `source_deed_id` set to the deed. A deed sitting in `PENDING_PAYMENT` has reserved but not yet fully conveyed the plot.

**Transfer and acceptance.** An `ISSUED` deed can change hands. A `Registrar` proposes a transfer by supplying a `new_holder_id`; the deed moves `ISSUED` → `TRANSFER_PENDING` and stores that id as `pending_new_holder_id`. The proposed holder must reference an existing `RightHolder` — otherwise `ERR_HOLDER_NOT_FOUND` — and must differ from the current `holder_id`. Acceptance is performed by the incoming holder acting as themselves: the acting `RightHolder`'s `X-User-ID` must equal the deed's `pending_new_holder_id`, otherwise the acceptance is rejected with `ERR_NOT_PENDING_HOLDER`. On acceptance the deed moves `TRANSFER_PENDING` → `ISSUED`, `holder_id` is updated to the pending holder, and `pending_new_holder_id` is cleared. Because acceptance returns the deed to `ISSUED`, a deed may be transferred repeatedly over its life.

**Surrender.** A `Registrar` may surrender a deed, reclaiming its plot. Surrender is only permitted when the plot has no interment in `SCHEDULED`, `OPENED`, or `COMPLETED` status; an attempt while such an active interment exists is rejected with `ERR_PLOT_OCCUPIED`. Surrendering an `ISSUED` deed (whose plot is `SOLD`) moves the deed to the terminal `SURRENDERED`, returns the plot to `AVAILABLE`, cancels any non-terminal marker permits on the plot (those in `APPLIED` or `APPROVED` move to `CANCELLED`), posts a `DISBURSEMENT` care-fund entry reversing the deed's original contribution, and issues a refund invoice. Surrendering while the plot is still merely `RESERVED` likewise returns the plot to `AVAILABLE` and cancels its non-terminal marker permits.

Deeds can be listed and filtered by `plot_id`, `holder_id`, `pending_new_holder_id`, and `status`, and individual deeds are retrievable by id.

### 3.3. Scheduling an Interment: Fees, Capacity, and Crews

A `Registrar` schedules an interment — the opening and closing of a grave — by creating an `Interment` that names the `plot_id` receiving it, the `decedent_id` being interred, and the `deed_id` authorizing it. The referenced deed must be `ISSUED`; if it is in any other state the scheduling is rejected with `ERR_DEED_NOT_ISSUED`. The request also carries an `interment_type` of `BURIAL`, `ENTOMBMENT`, or `INURNMENT`; a `depth_position` (the depth or tier index within the plot, where 1 is the first/top position, at least 1); the `scheduled_date` as an ISO `YYYY-MM-DD` calendar date; and the crew time window as `scheduled_start` and `scheduled_end`, both ISO 8601 UTC datetimes, with `scheduled_end` strictly after `scheduled_start`. On success the interment's `operational_status` is `SCHEDULED` and its `billing_status` is `INVOICED`, `day_type` and `service_fee_cents` are computed, the plot's `interments_used` increases by one, and an `INTERMENT_SERVICE` invoice is issued with its id stored as `service_invoice_id`.

**Temporal, capacity, and booking gates.** The `scheduled_date` may not be earlier than the current logical-clock date, otherwise `ERR_DATE_IN_PAST`. The plot's `interments_used` must be strictly below its `interment_capacity`, otherwise `ERR_PLOT_CAPACITY`. Two distinct interval rules then guard the crew calendar. First, a plot may hold at most one non-cancelled interment on any single `scheduled_date`; a second booking on the same day is rejected with `ERR_PLOT_DOUBLE_BOOKED`. Second, the crew time window is treated as a half-open interval from `scheduled_start` up to but not including `scheduled_end`, padded on each side by a buffer of 60 minutes: for the same calendar day, the count of existing interments (those with `operational_status` of `SCHEDULED`, `OPENED`, or `COMPLETED`) whose buffered window intersects the new buffered window must be strictly less than the cemetery's `crew_team_count`, otherwise `ERR_CREW_UNAVAILABLE`. Two windows intersect when the first starts before the second's end-plus-buffer and the second starts before the first's end-plus-buffer; windows that merely touch at an endpoint do not overlap, while any gap smaller than the 60-minute buffer does count as an overlap.

**The service fee.** The `service_fee_cents` is the sum of four components. The base is determined by `plot_type`: 90,000 cents for `GRAVE`, 120,000 for `LAWN_CRYPT`, 45,000 for `NICHE`, and 150,000 for `MAUSOLEUM`. The depth surcharge is 0 when `depth_position` is 1, 15,000 cents when it is exactly 2, and 30,000 cents for any depth of 3 or greater. The day surcharge derives from `day_type`, which is `HOLIDAY` when `scheduled_date` falls on one of the recognized holidays (2026-01-01, 2026-07-04, 2026-11-26, 2026-12-25), `WEEKEND` when it falls on a Saturday or Sunday, and `WEEKDAY` otherwise; a `HOLIDAY` adds 35,000 cents and a `WEEKEND` adds 20,000 cents, and when a date would qualify as both, the holiday surcharge dominates and the weekend surcharge is not also applied. The short-notice surcharge of 25,000 cents applies when the number of whole days from the current logical-clock date to the `scheduled_date` is strictly less than 3, and is otherwise 0. The four components are summed to the final fee; as noted in §2.6, the `INTERMENT_SERVICE` invoice carries one taxable line per non-zero component, in the order base, depth, day, short-notice.

Interments can be listed and filtered by `plot_id`, `decedent_id`, `deed_id`, `scheduled_date`, and `operational_status`, and read individually by id.

### 3.4. Opening, Closing, and Cancelling: the Two Axes of an Interment

An interment evolves along two independent axes. The `operational_status` axis tracks the physical work — `SCHEDULED`, `OPENED`, `COMPLETED`, and the terminal `CANCELLED` and `DISINTERRED`. The `billing_status` axis tracks money — `INVOICED`, `PAID`, and `VOIDED` — and moves on its own: it becomes `PAID` when the service invoice is paid and `VOIDED` when the service invoice is voided on cancellation, entirely independently of where the operational axis stands.

A `GroundsForeman` opens a grave, moving `operational_status` from `SCHEDULED` to `OPENED`, only after two conditions hold: the interment's service invoice has been paid, meaning its `billing_status` is `PAID` (otherwise `ERR_INVOICE_UNPAID`), and the current logical-clock date is on or after the `scheduled_date` (otherwise `ERR_TOO_EARLY_TO_OPEN`). Opening leaves the billing axis untouched. The same foreman later completes (closes) the grave, moving `OPENED` to `COMPLETED`.

A `Registrar` may cancel an interment while it is `SCHEDULED` or `OPENED`, moving it to the terminal `CANCELLED`. Cancellation decrements the plot's `interments_used` by one, restoring occupancy, and voids the service invoice while setting `billing_status` to `VOIDED` (when the interment was `SCHEDULED`; from `OPENED`, the service invoice is voided if it has not already been paid). A schedule paired with its cancellation leaves the plot's occupancy count exactly where it started.

### 3.5. Foundation and Marker Permits

A `Registrar` or a `RightHolder` applies for a foundation/marker permit by creating a `MarkerPermit` that names the `plot_id` where the foundation is installed and the `deed_id` authorizing it, a `marker_type` of `FLAT`, `UPRIGHT`, or `MONUMENT`, and the foundation footprint as `foundation_length_in` and `foundation_width_in`, both integers greater than 0. A `RightHolder` applying must own the referenced deed. On application the permit is `APPLIED`, its `foundation_fee_cents` is computed from `marker_type` — 15,000 cents for `FLAT`, 30,000 for `UPRIGHT`, and 60,000 for `MONUMENT` — and a `MARKER_FOUNDATION` invoice is issued with its id stored as `foundation_invoice_id`.

A permit's `status` moves through `APPLIED`, `APPROVED`, `INSTALLED`, and the terminal `REJECTED`, `CANCELLED`, and `DECOMMISSIONED`. A `CemeteryDirector` approves a permit, moving `APPLIED` to `APPROVED`, only when the referenced deed's status is `ISSUED`, otherwise `ERR_DEED_NOT_ISSUED`. The director may instead reject an `APPLIED` permit, moving it to `REJECTED` and voiding its `MARKER_FOUNDATION` invoice. A `GroundsForeman` records installation, moving `APPROVED` to `INSTALLED`, only when the `MARKER_FOUNDATION` invoice has been paid (otherwise `ERR_INVOICE_UNPAID`) and the plot has an interment whose `operational_status` is `COMPLETED` (otherwise `ERR_NO_COMPLETED_INTERMENT`).

Marker permits also move under system cascades. When a plot is reclaimed by a deed surrender, its non-terminal permits — those in `APPLIED` or `APPROVED` — move to `CANCELLED`, and any still-unpaid `MARKER_FOUNDATION` invoice is voided. When the interment on a plot is disinterred, an `INSTALLED` permit on that plot moves to `DECOMMISSIONED`. Permits can be listed and filtered by `plot_id`, `deed_id`, and `status`.

### 3.6. Disinterment: Consent, Clearance, and Execution

Disinterment is the most tightly controlled workflow in the system, combining a parallel consent gate with a segregation-of-duties gate. A `Registrar` requests a disinterment by creating a `DisintermentAuthorization` that names the `interment_id` to be disinterred — which must be a `COMPLETED` interment, otherwise the request fails referentially — a `reason`, a `disinterment_type` of `RELOCATION` or `REMOVAL`, and, when the type is `RELOCATION`, an optional `target_plot_id` naming the destination plot. On request the authorization is `REQUESTED`, its `health_cleared` and `nok_consented` flags both begin `false`, and a `DISINTERMENT` invoice carrying a single taxable line of the flat disinterment fee of 200,000 cents is issued with its id stored as `disinterment_invoice_id`.

Two independent branches must both complete before approval — a fork-join. On branch A, a `HealthOfficer` records public-health clearance, setting `health_cleared` to `true`; this is permitted only while `health_cleared` is still `false`, otherwise `ERR_ALREADY_RECORDED`. On branch B, the next-of-kin — the `RightHolder` who holds the interment's deed — records consent, setting `nok_consented` to `true`; this too is permitted only while `nok_consented` is still `false`, otherwise `ERR_ALREADY_RECORDED`. Both leave the authorization in `REQUESTED`; they are order-independent and may arrive in either sequence.

A `CemeteryDirector` then either approves or denies the request from `REQUESTED`. Approval is the join gate: it is permitted only when both `health_cleared` and `nok_consented` are `true`, otherwise `ERR_CONSENT_INCOMPLETE`. On approval the authorization moves to `APPROVED` and the director's `X-User-ID` is recorded as `approved_by_user_id`. Denial moves the authorization to the terminal `DENIED` and voids its `DISINTERMENT` invoice.

A `Registrar` executes an `APPROVED` authorization, moving it to the terminal `EXECUTED`. Execution requires that the `DISINTERMENT` invoice has been paid (otherwise `ERR_INVOICE_UNPAID`) and that the executing `Registrar`'s `X-User-ID` differs from the recorded `approved_by_user_id` (otherwise `ERR_SEGREGATION_OF_DUTIES`). Execution cascades: the linked interment's `operational_status` moves to the terminal `DISINTERRED`, the plot's `interments_used` decrements by one, any `INSTALLED` marker permit on the plot moves to `DECOMMISSIONED`, and a `DISBURSEMENT` care-fund entry equal to the computed `settlement_cents` is posted.

The settlement depends on the disinterment variant and is drawn from the perpetual-care contribution originally pinned on the interment's deed (reached via the interment's `deed_id`). For a `RELOCATION`, `settlement_cents` is that contribution multiplied by 50% (0.50) and rounded half-up — the care funds follow the remains to the new resting place. For a `REMOVAL`, it is that contribution multiplied by 25% (0.25) and rounded half-up — a partial refund, with the remainder retained by the fund. The same contribution therefore settles to a different amount depending on `disinterment_type`. Authorizations can be listed and filtered by `interment_id`, `target_plot_id`, and `status`.

### 3.7. Billing, Payments, and the Care-Fund Ledger

Every deed sale, interment service, marker foundation, and disinterment produces an `Invoice` whose composition and totals follow §2.6. A `FinanceOfficer` settles an invoice by recording a `Payment` that names the `invoice_id`, an `amount_cents` tendered, and a `method` of `CARD`, `CHECK`, `CASH`, or `ACH`. The invoice must be in `ISSUED` state to accept a payment; a payment attempted against an invoice that is not `ISSUED` is rejected with `ERR_INVOICE_NOT_OPEN`. The tendered `amount_cents` must equal the invoice's `total_cents` exactly, otherwise `ERR_PAYMENT_AMOUNT_MISMATCH`. On success the invoice moves to `PAID`, and the subject-specific cascade fires according to `subject_type`: a paid `DEED_SALE` issues the deed (`PENDING_PAYMENT` → `ISSUED`), advances the plot to `SOLD`, and posts the `CONTRIBUTION` care-fund entry; a paid `INTERMENT_SERVICE` advances the interment's `billing_status` to `PAID` while leaving its `operational_status` unchanged. Payments can be listed and filtered by `invoice_id` and read individually by id.

A `FinanceOfficer` may also void an `ISSUED` invoice under maker-checker control: the acting officer's `X-User-ID` must differ from the invoice's `issued_by_user_id`, otherwise `ERR_SEGREGATION_OF_DUTIES`; a void attempted on an invoice that is not `ISSUED` is rejected with `ERR_INVOICE_NOT_OPEN`.

Finally, a `FinanceOfficer` posts perpetual-care ledger entries directly, supplying the `cemetery_id`, the `entry_type`, a non-negative `amount_cents`, an optional `source_deed_id`, and an optional `note`. As established in §2.7, the cemetery's balance is recomputed from the full append-only history on every post, and a `DISBURSEMENT` that would carry the balance below zero is rejected with `ERR_CARE_FUND_INSUFFICIENT`. Care-fund entries can be listed and filtered by `cemetery_id`, `source_deed_id`, and `entry_type`, and read individually by id.

## 4. Endpoint Definitions

Operations that create a new stand-alone resource return `201 Created`; operations that modify an existing resource, including state-transition actions, return `200 OK`. The logical-clock setter returns `200 OK`. All paths are mounted under `/cemetery-mgmt`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/cemetery-mgmt/cemeteries` | Create a cemetery | CemeteryDirector |
| GET | `/cemetery-mgmt/cemeteries/{cemetery_id}` | Get a cemetery (includes fund balance) | Registrar, GroundsForeman, FinanceOfficer, HealthOfficer, CemeteryDirector, RightHolder |
| POST | `/cemetery-mgmt/plots` | Create a plot in a cemetery | Registrar |
| GET | `/cemetery-mgmt/plots/{plot_id}` | Get a plot | Registrar, GroundsForeman, FinanceOfficer, HealthOfficer, CemeteryDirector, RightHolder |
| GET | `/cemetery-mgmt/plots` | List/search plots | Registrar, GroundsForeman, FinanceOfficer, HealthOfficer, CemeteryDirector, RightHolder |
| POST | `/cemetery-mgmt/plots/{plot_id}/retire` | Retire an empty available plot | CemeteryDirector |
| POST | `/cemetery-mgmt/holders` | Create a right-holder record | Registrar |
| GET | `/cemetery-mgmt/holders/{holder_id}` | Get a right-holder | Registrar, FinanceOfficer, CemeteryDirector, RightHolder |
| POST | `/cemetery-mgmt/decedents` | Create an immutable decedent record | Registrar |
| GET | `/cemetery-mgmt/decedents/{decedent_id}` | Get a decedent record | Registrar, GroundsForeman, FinanceOfficer, HealthOfficer, CemeteryDirector, RightHolder |
| GET | `/cemetery-mgmt/decedents` | Genealogy lookup (search decedents) | Registrar, GroundsForeman, FinanceOfficer, HealthOfficer, CemeteryDirector, RightHolder |
| POST | `/cemetery-mgmt/deeds` | Sell right-of-interment on a plot (OCC on plot) | Registrar |
| GET | `/cemetery-mgmt/deeds/{deed_id}` | Get a deed | Registrar, FinanceOfficer, CemeteryDirector, RightHolder |
| GET | `/cemetery-mgmt/deeds` | List deeds | Registrar, FinanceOfficer, CemeteryDirector, RightHolder |
| POST | `/cemetery-mgmt/deeds/{deed_id}/transfer` | Propose transfer of a deed to a new holder | Registrar |
| POST | `/cemetery-mgmt/deeds/{deed_id}/accept-transfer` | New holder accepts transfer | RightHolder |
| POST | `/cemetery-mgmt/deeds/{deed_id}/surrender` | Surrender a deed; plot reclaimed | Registrar |
| POST | `/cemetery-mgmt/interments` | Schedule an interment (opening/closing) | Registrar |
| GET | `/cemetery-mgmt/interments/{interment_id}` | Get an interment | Registrar, GroundsForeman, FinanceOfficer, HealthOfficer, CemeteryDirector, RightHolder |
| GET | `/cemetery-mgmt/interments` | List interments | Registrar, GroundsForeman, FinanceOfficer, HealthOfficer, CemeteryDirector, RightHolder |
| POST | `/cemetery-mgmt/interments/{interment_id}/open` | Open the grave | GroundsForeman |
| POST | `/cemetery-mgmt/interments/{interment_id}/complete` | Close the grave | GroundsForeman |
| POST | `/cemetery-mgmt/interments/{interment_id}/cancel` | Cancel a scheduled/opened interment | Registrar |
| POST | `/cemetery-mgmt/disinterment-authorizations` | Request disinterment of a completed interment | Registrar |
| GET | `/cemetery-mgmt/disinterment-authorizations/{auth_id}` | Get a disinterment authorization | Registrar, HealthOfficer, CemeteryDirector, RightHolder |
| GET | `/cemetery-mgmt/disinterment-authorizations` | List disinterment authorizations | Registrar, HealthOfficer, CemeteryDirector, RightHolder |
| POST | `/cemetery-mgmt/disinterment-authorizations/{auth_id}/record-clearance` | Health officer records clearance (branch A) | HealthOfficer |
| POST | `/cemetery-mgmt/disinterment-authorizations/{auth_id}/record-consent` | Next-of-kin records consent (branch B) | RightHolder |
| POST | `/cemetery-mgmt/disinterment-authorizations/{auth_id}/approve` | Director approves (join gate) | CemeteryDirector |
| POST | `/cemetery-mgmt/disinterment-authorizations/{auth_id}/deny` | Director denies | CemeteryDirector |
| POST | `/cemetery-mgmt/disinterment-authorizations/{auth_id}/execute` | Registrar executes disinterment (cascade) | Registrar |
| POST | `/cemetery-mgmt/marker-permits` | Apply for a foundation/marker permit | Registrar, RightHolder |
| GET | `/cemetery-mgmt/marker-permits/{permit_id}` | Get a marker permit | Registrar, GroundsForeman, FinanceOfficer, CemeteryDirector, RightHolder |
| GET | `/cemetery-mgmt/marker-permits` | List marker permits | Registrar, GroundsForeman, FinanceOfficer, CemeteryDirector, RightHolder |
| POST | `/cemetery-mgmt/marker-permits/{permit_id}/approve` | Director approves marker permit | CemeteryDirector |
| POST | `/cemetery-mgmt/marker-permits/{permit_id}/install` | Grounds foreman records installation | GroundsForeman |
| POST | `/cemetery-mgmt/marker-permits/{permit_id}/reject` | Director rejects marker permit | CemeteryDirector |
| GET | `/cemetery-mgmt/invoices/{invoice_id}` | Get an invoice | Registrar, FinanceOfficer, CemeteryDirector, RightHolder |
| GET | `/cemetery-mgmt/invoices` | List invoices | Registrar, FinanceOfficer, CemeteryDirector, RightHolder |
| POST | `/cemetery-mgmt/invoices/{invoice_id}/void` | Void an issued invoice (maker-checker) | FinanceOfficer |
| POST | `/cemetery-mgmt/payments` | Record a payment settling an invoice | FinanceOfficer |
| GET | `/cemetery-mgmt/payments/{payment_id}` | Get a payment | Registrar, FinanceOfficer, CemeteryDirector |
| GET | `/cemetery-mgmt/payments` | List payments | Registrar, FinanceOfficer, CemeteryDirector |
| POST | `/cemetery-mgmt/care-fund-entries` | Post a perpetual-care ledger entry | FinanceOfficer |
| GET | `/cemetery-mgmt/care-fund-entries/{entry_id}` | Get a care-fund entry | FinanceOfficer, CemeteryDirector |
| GET | `/cemetery-mgmt/care-fund-entries` | List care-fund entries | FinanceOfficer, CemeteryDirector |
| POST | `/cemetery-mgmt/_clock/set_current_utc` | Set the server logical clock | Registrar, GroundsForeman, FinanceOfficer, HealthOfficer, CemeteryDirector |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_VALIDATION` | 400 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_PLOT_NOT_AVAILABLE` | 409 |
| `ERR_PLOT_OCCUPIED` | 409 |
| `ERR_DEED_NOT_ISSUED` | 409 |
| `ERR_HOLDER_NOT_FOUND` | 404 |
| `ERR_NOT_PENDING_HOLDER` | 403 |
| `ERR_CONSENT_INCOMPLETE` | 409 |
| `ERR_ALREADY_RECORDED` | 409 |
| `ERR_SEGREGATION_OF_DUTIES` | 409 |
| `ERR_NO_COMPLETED_INTERMENT` | 409 |
| `ERR_DATE_IN_PAST` | 422 |
| `ERR_TOO_EARLY_TO_OPEN` | 422 |
| `ERR_PLOT_CAPACITY` | 409 |
| `ERR_PLOT_DOUBLE_BOOKED` | 409 |
| `ERR_CREW_UNAVAILABLE` | 409 |
| `ERR_INVOICE_UNPAID` | 409 |
| `ERR_PAYMENT_AMOUNT_MISMATCH` | 409 |
| `ERR_INVOICE_NOT_OPEN` | 409 |
| `ERR_CARE_FUND_INSUFFICIENT` | 409 |
