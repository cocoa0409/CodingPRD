# Kids Consignment Popup API — Product Requirements Document

## 1. Introduction

A kids' consignment pop-up sale compresses an entire retail lifecycle into about a week: families register as consignors, tag and price their outgrown clothing and gear, drop everything off during a scheduled intake window, and watch the proceeds settle after the public sale closes. Behind the gymnasium folding tables sits a genuinely hard coordination problem. Inventory arrives from hundreds of independent sellers, each item must be inspected before it reaches the floor, volunteers staff the event in exchange for early-shopping privileges and discount tiers that depend on hours worked, markdown windows reprice the floor on later sale days, and at the end every consignor is owed a split of their actual sales minus fees — a number that must be projected live while the sale is running and then frozen, disputed, adjusted, and paid during settlement.

This document specifies the REST API that operates such an event end to end. It covers consignor registration and tag printing, drop-off slot booking and intake inspection with segregation of duties, volunteer shift management and the hours-based discount ladder, presale pass issuance, the point-of-sale ticket lifecycle with barcode scanning and per-line rounding, markdown pricing windows, unsold-item pickup and donation, and the settlement pipeline from provisional projection through finalization, dispute, and payout. A server-maintained logical clock gates every time-window rule so that the full event arc — from `DRAFT` through intake, presale, public sale, settlement, and close — can be exercised deterministically.

The audience is the engineering team building the service. Contract-level details (response envelopes, pagination, error identifiers, header names) are stated precisely in Section 2; business rules are deliberately woven through the workflow narratives of Section 3, and the reader is expected to reconstruct each operation's complete behavior from both.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request carries two identity headers: `X-User-ID` and `X-User-Role`. A request missing either header, or presenting a role value outside the declared set, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT` (HTTP 400) before any other evaluation. A request whose role is not permitted for the target endpoint, or that fails an entity-backed ownership check, is rejected with `ERR_FORBIDDEN` (HTTP 403).

Six roles exist, spelled exactly as follows:

- `Anonymous` — an unauthenticated registrant. `X-User-ID` is an opaque identifier not tied to any persisted entity; the role may only self-register consignors and volunteers.
- `EventOrganizer` — runs the sale. `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server does not compare it to any entity's `id`.
- `Consignor` — a seller. When `X-User-Role` is `Consignor`, `X-User-ID` is the `id` of the acting `Consignor`; ownership checks on any resource that references a `Consignor` compare the resource's foreign-key field (such as `consignor_id`, whether it arrives in the path or the body) to `X-User-ID`. A consignor may act only on their own items, bookings, and settlements. That restriction binds single-resource reads and mutations; list endpoints are not ownership-filtered, except the settlement list, which shows a consignor only their own settlements.
- `Volunteer` — a shift worker. When `X-User-Role` is `Volunteer`, `X-User-ID` is the `id` of the acting `Volunteer`, and ownership checks on signups compare the signup's `volunteer_id` to `X-User-ID`. A volunteer may act only on their own signups. As with consignors, the restriction binds single-resource reads and mutations; the signups list is not ownership-filtered.
- `Inspector` — a volunteer acting in the inspection capacity. When `X-User-Role` is `Inspector`, `X-User-ID` is the `id` of the acting `Volunteer`, exactly as for the `Volunteer` role; the server records it as `inspector_id` on each `InspectionRecord` the inspector creates, and segregation-of-duties checks compare the volunteer's `linked_consignor_id` against the inspected item's owning consignor.
- `Cashier` — a point-of-sale operator. `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server records it as `cashier_id` on each `POSTransaction` the cashier opens, but never compares it to any entity's `id`. A cashier may void only transactions that are still `OPEN`; a cashier attempting to void a `COMPLETED` transaction is rejected with `ERR_FORBIDDEN`.

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
- The `api_request_timestamp` is a server-generated ISO 8601 UTC timestamp with three fractional digits, taken from wall-clock time (never the logical clock of §2.5).
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
- Requests to an unknown path surface `ERR_NOT_FOUND` (HTTP 404), an unsupported method on a known path surfaces `ERR_METHOD_NOT_ALLOWED` (HTTP 405), and an unexpected server failure surfaces `ERR_INTERNAL` (HTTP 500), all in this same envelope.

### 2.3. Pagination

All list endpoints accept two query parameters: `limit` and `offset`. The `limit` parameter defaults to 10; a value below 1 is clamped to 1 and a value above 100 is clamped to 100, and a non-integer value falls back to the default. The `offset` parameter defaults to 0; a negative value is clamped to 0 and a non-integer value falls back to 0. List responses sort by `created_at` ascending, breaking ties by insertion order, and the `meta` object of a list response carries `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Resource Identity and Common Fields

Every resource is addressed by its `id`, a server-minted UUID with no type prefix, supplied as a path variable wherever an endpoint targets one resource. All primary entities — `SaleEvent`, `MarkdownRule`, `Consignor`, `Volunteer`, `DropOffSlot`, `DropOffBooking`, `Item`, `VolunteerShift`, `ShiftSignup`, `PresalePass`, `POSTransaction`, and `Settlement` — additionally carry `created_at` and `updated_at` (ISO 8601 UTC timestamps with three fractional digits) and a `version` integer that starts at 1 on creation — with `created_at` and `updated_at` initially equal — and increments by exactly 1 on every mutation of that resource. Entity `created_at` and `updated_at` values are stamped from the logical clock of §2.5, not from wall-clock time. Two entities are deliberately lighter: `InspectionRecord` and `TransactionLine` carry only `id` and `created_at`; both `updated_at` and `version` are absent from them, and no operation that touches them reports a version.

### 2.5. The Logical Clock

The server evaluates every temporal rule against a logical clock, never against wall-clock time. At startup, before any clock call has been made, the logical clock reads exactly 2026-05-01T00:00:00Z, and it never falls back to wall-clock time thereafter. An `EventOrganizer` may advance the logical clock by submitting a `to_iso8601` instant (ISO 8601 UTC); any parseable instant is accepted, including one behind the current reading, while an unparseable value is rejected with `ERR_VALIDATION` (HTTP 400); the response reports the new `current_utc`. Phase gates, intake windows, inspection deadlines, pickup deadlines, markdown effectiveness, and no-show eligibility all read this clock.

### 2.6. Money, Rounding, and Per-Line Precision

All monetary quantities are integer cents. Every monetary division — markdown pricing at scan time, presale-pass discount application, commission computation, and the per-item sell-through projection used in provisional settlements — rounds half-up to whole cents. The rounding order for transaction totals is pinned: each line is rounded to cents first, and the rounded line values are then summed. The alternative order — summing raw unrounded line values and rounding once at the end — is forbidden. Percentages (discount rates, markdown rates, split percentages) are integers. Volunteer hours are numbers carried to two decimal places. Wherever this document quotes a dollar figure it is explanatory only; the wire format is always cents, so a $2.00 minimum tag price means 200 cents and a $10.00 supply fee means 1000 cents.

### 2.7. Event Phases as a Global Gate

A `SaleEvent` progresses through a strictly linear phase ladder: `DRAFT` → `INTAKE_OPEN` → `INTAKE_CLOSED` → `PRESALE_DAY` → `SALE_ACTIVE` → `SETTLEMENT` → `CLOSED`, the terminal phase. Phases advance only through an explicit advance-phase action naming the exact next phase in `to_phase`; attempting to skip a phase, or to advance into any phase other than the immediate successor, is rejected with `ERR_EVENT_PHASE_MISMATCH` (HTTP 409). The same error guards every phase-gated operation elsewhere in the system: tagging an item or registering a consignor or volunteer is permitted only in `DRAFT` or `INTAKE_OPEN`; booking a drop-off slot is permitted in `DRAFT` or `INTAKE_OPEN`, while checking a booking in and dropping items off require `INTAKE_OPEN`; inspection requires `INTAKE_OPEN` or `INTAKE_CLOSED`; markdown rule creation is permitted up to and including `PRESALE_DAY`; opening a POS ticket requires `PRESALE_DAY` or `SALE_ACTIVE`; settlement generation requires `SALE_ACTIVE` or `SETTLEMENT`; finalization requires `SETTLEMENT`; unsold-item pickup requires `SETTLEMENT`; and voiding a completed transaction is permitted only in `PRESALE_DAY` or `SALE_ACTIVE`. Phase advances themselves carry clock preconditions: advancing into `INTAKE_OPEN` requires the clock to have reached `intake_start`, into `INTAKE_CLOSED` `intake_end`, into `PRESALE_DAY` `presale_start`, into `SALE_ACTIVE` `sale_start`, and into `SETTLEMENT` `sale_end`; an advance whose clock precondition is unmet is rejected with `ERR_EVENT_PHASE_MISMATCH` (HTTP 409).

### 2.8. Request Validation Order

When several validation rules could reject the same request, the server evaluates them in a fixed precedence so that the surfaced error is deterministic. The order is: first, the identity-header check (`ERR_MISSING_OR_INVALID_USER_CONTEXT`); second, role permission and entity-backed ownership (`ERR_FORBIDDEN`) — ownership rules decidable from the request alone (a path id or a body's `consignor_id`/`volunteer_id` compared to `X-User-ID`) fire at this step, while ownership rules that must read the target resource fire immediately after that resource's existence check; third, existence of every referenced resource, validated left-to-right along the path and then the body — a missing sale event surfaces `ERR_SALE_EVENT_NOT_FOUND`, and the same pattern yields `ERR_CONSIGNOR_NOT_FOUND`, `ERR_ITEM_NOT_FOUND`, `ERR_SLOT_NOT_FOUND`, `ERR_BOOKING_NOT_FOUND`, `ERR_VOLUNTEER_NOT_FOUND`, `ERR_SHIFT_NOT_FOUND`, `ERR_SIGNUP_NOT_FOUND`, `ERR_PASS_NOT_FOUND`, `ERR_TRANSACTION_NOT_FOUND`, `ERR_LINE_NOT_FOUND`, `ERR_SETTLEMENT_NOT_FOUND`, `ERR_MARKDOWN_RULE_NOT_FOUND`, `ERR_BARCODE_NOT_FOUND` (a scanned barcode matching no item of the transaction's event), and `ERR_INSPECTION_RECORD_NOT_FOUND`; fourth, the event phase gate (`ERR_EVENT_PHASE_MISMATCH`); fifth, the target entity's lifecycle state (the `ERR_*_WRONG_STATE` family, plus `ERR_TRANSACTION_NOT_OPEN`, `ERR_PASS_NOT_ACTIVE`, and `ERR_SETTLEMENTS_LOCKED`); sixth, segregation of duties on inspection (`ERR_INSPECTION_SELF_DEALING`); seventh, clock-window and interval rules (`ERR_INTAKE_WINDOW_CLOSED`, `ERR_INSPECTION_DEADLINE_PASSED`, `ERR_PICKUP_WINDOW_CLOSED`, `ERR_SHIFT_OVERLAP`, `ERR_INVALID_TIME_WINDOW`, `ERR_MARKDOWN_WINDOW_OVERLAP`, `ERR_NO_SHOW_TOO_EARLY`); eighth, capacity, uniqueness, format, and guard constraints; and ninth, at checkout only, tender sufficiency (`ERR_INSUFFICIENT_TENDER`). An inspection request, for example, that arrives in the wrong phase and also violates self-dealing surfaces `ERR_EVENT_PHASE_MISMATCH`, because the phase gate outranks the segregation check; likewise a drop-off attempted by a consignor with no checked-in booking outside the intake window surfaces `ERR_INTAKE_WINDOW_CLOSED`, because the window check outranks the booking guard.

### 2.9. Optimistic Concurrency Control

Exactly one endpoint participates in optimistic concurrency control: regenerating an event's settlements. The request must carry `expected_sale_event_version`, a non-optional field holding the client's last observed `version` of the `SaleEvent`. If that value does not match the event's current `version` — because another mutation has advanced the event since the client last read it — the request is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the client from superseding drafts built from newer sales data. No other endpoint accepts a version field; operations not named here must not require one.

### 2.10. Derived Counters and Reconciliation Invariants

Several fields are never accepted as input; the server recomputes them on every relevant mutation. A `Consignor` carries `sold_count`, `unsold_count`, `rejected_count`, and `sold_gross_cents`; a `Volunteer` carries `completed_hours`, `projected_hours`, and `projected_discount_pct`; a `DropOffSlot` carries `booked_count`; a `VolunteerShift` carries `signed_up_count`; a `POSTransaction` carries `subtotal_cents`, `discount_cents`, `total_cents`, and `change_cents`; a `SaleEvent` carries `sold_gross_cents`. Two invariants must hold at every observable instant. First, the money invariant: the event's `sold_gross_cents` always equals the sum of `total_cents` over the event's `COMPLETED` transactions, and always equals the sum of `sold_gross_cents` over the event's consignors — checkout adds a transaction's total and voiding a completed transaction subtracts it, a compensating pair that leaves the conserved quantity consistent. Second, the sellable-inventory invariant: the count of the event's items in `ON_FLOOR`, `IN_CART`, or `SOLD` status changes only through real business events; scanning an item (`ON_FLOOR` → `IN_CART`) and removing the line (`IN_CART` → `ON_FLOOR`) leave the count unchanged, as do checkout and the void of a completed transaction. No item transition ever creates or destroys an item row: after creation, the total item count per event is constant.

## 3. Business Logic & Workflows

### 3.1. Configuring the Sale and Its Markdown Calendar

An `EventOrganizer` begins by creating the sale itself, supplying a human-readable `name` and the full temporal skeleton: `intake_start` and `intake_end` delimit the drop-off window (the end is exclusive), `presale_start` and `presale_end` delimit the presale, `sale_start` and `sale_end` delimit the public sale, and `pickup_deadline` bounds unsold-item retrieval. A new event is born in phase `DRAFT` with `sold_gross_cents` at 0. The event list can be filtered by `phase`.

Markdown windows reprice the floor on later sale days. Creating a `MarkdownRule` takes the target `sale_event_id`, an `effective_from` instant (inclusive), an `effective_to` instant (exclusive), and a `discount_pct` integer percentage, stored as supplied — the server applies no range validation to it. The window must be internally valid — `effective_from` strictly before `effective_to` — or the create is rejected with `ERR_INVALID_TIME_WINDOW`; the same error applies to any windowed resource whose start is not strictly before its end. Within one event, markdown windows must not overlap: a new rule is rejected with `ERR_MARKDOWN_WINDOW_OVERLAP` whenever an existing rule's `effective_from` falls before the new rule's `effective_to` and the new rule's `effective_from` falls before the existing rule's `effective_to`. Because windows are half-open, back-to-back windows — one rule's `effective_to` exactly equal to the next rule's `effective_from` — are allowed, and this non-overlap guarantee means at most one markdown rule is ever in effect at a scan instant. Markdown creation is phase-gated to `DRAFT`, `INTAKE_OPEN`, `INTAKE_CLOSED`, or `PRESALE_DAY`; attempting it later yields `ERR_EVENT_PHASE_MISMATCH`. Organizers and cashiers can list rules, filtering by `sale_event_id`.

### 3.2. Onboarding: Consignor and Volunteer Registration

Registration is self-service: an `Anonymous` caller registers a consignor by providing the target `sale_event_id`, a `full_name`, and an `email`, and the same role registers volunteers with an identical payload plus an optional `linked_consignor_id`. Registration is open only while the event is in `DRAFT` or `INTAKE_OPEN`. A new consignor arrives in status `ACTIVE` and is immediately assigned a `consignor_code`: the letter "C" followed by a zero-padded four-digit sequence number, where the sequence is the consignor's one-based registration order within the event, ordered by `created_at` ascending — the first consignor of an event receives C0001.

The volunteer record's `linked_consignor_id` is nullable and is set when the volunteer also sells at the event. This single link drives two otherwise unrelated rules: it bars the volunteer from inspecting their own consigned merchandise (§3.5), and it qualifies the consignor for a payout-split bonus once the volunteer has banked enough hours (§3.9).

A consignor may leave the event through withdrawal — either the organizer or the consignor themself may request it — but only while they own zero items; a withdrawal requested for a consignor with any items is rejected with `ERR_CONSIGNOR_HAS_ITEMS`. Successful withdrawal moves the consignor from `ACTIVE` to `WITHDRAWN` and bumps the consignor's `version`. Requesting withdrawal for a consignor already `WITHDRAWN` is an idempotent no-op: the call succeeds, returns the record unchanged, and does not bump `version`. Organizers can list consignors with `sale_event_id` and `status` filters, and volunteers with `sale_event_id` and `linked_consignor_id` filters; a consignor may read their own record, and a volunteer or inspector may read their own volunteer record.

### 3.3. Tagging and Pricing Merchandise

Once registered, a consignor tags items. Each new item names its owning `consignor_id`, a `title` for the tag, a `category` — conventionally one of `CLOTHING`, `TOYS`, `BOOKS`, `GEAR`, `MATERNITY`, or `OTHER`, though the supplied value is stored without validation — a `price_cents` tag price, and optionally a `size` label (defaulting to none), a `discount_eligible` flag (defaulting to true — the familiar "reduce" flag on the tag), and a `donate_flag` (defaulting to false) that marks the item for automatic donation at close. Tagging is permitted in `DRAFT` or `INTAKE_OPEN`. The tag price must be at least 200 cents ($2.00) — a lower price is rejected with `ERR_PRICE_BELOW_MINIMUM` (HTTP 400) — and must be a whole multiple of 50 cents, or the create fails with `ERR_PRICE_INCREMENT_VIOLATION` (HTTP 400). A price violating both rules surfaces `ERR_PRICE_BELOW_MINIMUM`, the minimum check being evaluated first.

The server, not the consignor, assigns each item's identity on the floor. The item's `sale_event_id` is copied from its consignor at creation, and its `barcode` is built from the consignor's `consignor_code`, a hyphen, and a zero-padded four-digit sequence reflecting the item's one-based creation order for that consignor by `created_at` ascending — so the first item tagged by consignor C0001 carries barcode C0001-0001. Barcodes are unique per event. A new item starts in status `TAGGED`; items can be listed with `sale_event_id`, `consignor_id`, `status`, and `barcode` filters, and each item's `reject_reason` stays null unless a failed inspection later sets it.

### 3.4. Drop-Off Appointments and Intake

Intake runs on appointments. An organizer creates `DropOffSlot` records with a `sale_event_id`, a `start_time`, an `end_time` (exclusive), and a `capacity` (stored as supplied; no minimum is enforced), while the event is in `DRAFT` or `INTAKE_OPEN`. Capacity is aggregate, not pairwise: a slot's `booked_count` counts its bookings in `BOOKED` or `CHECKED_IN` status, and a new booking is rejected with `ERR_SLOT_FULL` only when the slot's `booked_count` already equals its `capacity` — the booking that would bring the count exactly up to capacity is allowed, and the next one fails.

A consignor books a slot by submitting the `slot_id` and their own `consignor_id`, during `DRAFT` or `INTAKE_OPEN`. Each consignor may hold at most one active booking per event — a second booking while one is already `BOOKED` or `CHECKED_IN` is rejected with `ERR_DUPLICATE_ACTIVE_BOOKING`. The capacity check outranks the duplicate-booking guard: a booking that would violate both surfaces `ERR_SLOT_FULL`. A successful booking starts in `BOOKED` and raises the slot's `booked_count` by one. Cancellation, available to the organizer or the owning consignor while the booking is still `BOOKED`, moves it to `CANCELLED` and decrements the slot's `booked_count` — a compensation that frees aggregate capacity. At the venue, an organizer checks the booking in, moving `BOOKED` to `CHECKED_IN`; this requires the event to be in `INTAKE_OPEN` and the booking to be in `BOOKED` (otherwise `ERR_BOOKING_WRONG_STATE`), and it leaves `booked_count` unchanged because a checked-in booking still counts. Bookings can be listed with `slot_id`, `consignor_id`, and `status` filters.

With a checked-in booking in hand, the consignor drops items off. Dropping off requires three things, each with its own failure: the event must be in `INTAKE_OPEN` (`ERR_EVENT_PHASE_MISMATCH`); the logical clock must lie within the intake window — at or after `intake_start` and strictly before `intake_end` — or the request fails with `ERR_INTAKE_WINDOW_CLOSED`; and the consignor must hold a booking in `CHECKED_IN` for the event, or the drop-off fails with `ERR_NO_CHECKED_IN_BOOKING`. A successful drop-off moves the item from `TAGGED` to `DROPPED_OFF` and triggers recomputation of the consignor's counters.

When intake closes — the organizer advancing the event from `INTAKE_OPEN` to `INTAKE_CLOSED`, permitted once the clock has reached `intake_end` — the system sweeps every remaining booking: all bookings still `BOOKED` become `NO_SHOW`, and all bookings still `CHECKED_IN` become `COMPLETED`; in both cases the slot's `booked_count` is decremented by one per booking, and each booking's `version` bumps. The event's `version` increments by 1 with this and every other phase advance.

### 3.5. Inspection and the Segregation of Duties

Every dropped-off item passes through inspection before it may reach the floor. An `Inspector` submits an `outcome` of exactly `PASS` or `FAIL` — any other value is rejected with `ERR_VALIDATION` (HTTP 400); a `FAIL` submission should carry `reasons` describing the rejection, which are copied verbatim onto the item's `reject_reason` (a `FAIL` without reasons is accepted and leaves `reject_reason` null), while `reasons` is stored as null on a pass. A successful inspection returns the updated item object in the response's `data` field. Inspection is permitted while the event is in `INTAKE_OPEN` or `INTAKE_CLOSED`, the item must currently be `DROPPED_OFF` (otherwise `ERR_ITEM_WRONG_STATE`), and the logical clock must sit strictly before `presale_start` — an inspection attempted at or after the presale opens is rejected with `ERR_INSPECTION_DEADLINE_PASSED`.

Segregation of duties is the domain's core integrity rule: the inspector's volunteer record must not be linked to the consignor who owns the item. If the acting volunteer's `linked_consignor_id` equals the item's `consignor_id`, the inspection is rejected with `ERR_INSPECTION_SELF_DEALING` (HTTP 403).

Every inspection, pass or fail, creates an `InspectionRecord` naming the `item_id`, the `inspector_id` (taken from the inspector's `X-User-ID`), the `outcome`, and the `reasons`. A passing inspection moves the item `DROPPED_OFF` → `ACCEPTED`. A failing inspection moves it `DROPPED_OFF` → `REJECTED`, copies the reasons onto the item's `reject_reason`, and triggers recomputation of the consignor's `rejected_count` — a number that later costs real money at settlement, since each rejected item carries a fee. Inspection records form an audit trail that organizers and inspectors can list, filtered by `item_id` or `inspector_id`; because records are immutable audit rows, they carry `id` and `created_at` only, with no `updated_at` or `version`.

Inspection debt gates the presale: advancing the event from `INTAKE_CLOSED` to `PRESALE_DAY` requires the clock to have reached `presale_start` and also requires that no item of the event remain in `DROPPED_OFF`; any uninspected stragglers block the advance with `ERR_UNINSPECTED_ITEMS_REMAIN`. When the advance succeeds, every item in `ACCEPTED` moves to `ON_FLOOR`, processed in item `created_at` ascending order — that is the first cascade hop. Each moved item then triggers recomputation of its consignor's counters (the second hop) and, if a `DRAFT` settlement already exists for that consignor, recomputation of the settlement's provisional fields (the third hop).

### 3.6. Volunteer Shifts and the Discount Ladder

Volunteers staff the sale in exchange for discount tiers. An organizer defines each `VolunteerShift` with a `sale_event_id`, a free-text `role_name` (Inspector, Cashier, Floor, and the like), a `start_time`, an `end_time` (exclusive), and a `capacity` (stored as supplied; no minimum is enforced); shifts may be created while the event is in `DRAFT`, `INTAKE_OPEN`, or `INTAKE_CLOSED`.

A volunteer signs up by submitting the `shift_id` and their own `volunteer_id`, provided the event has not yet reached `SETTLEMENT` or `CLOSED`. Two guards protect the roster. Capacity: the shift's `signed_up_count` counts signups in `SIGNED_UP` or `CHECKED_IN`, and a signup arriving when that count already equals `capacity` is rejected with `ERR_SHIFT_FULL`. Overlap: a signup is rejected with `ERR_SHIFT_OVERLAP` when the volunteer already holds a signup in `SIGNED_UP` or `CHECKED_IN` whose shift overlaps the requested one — overlap meaning the existing shift's `start_time` falls before the new shift's `end_time` and the new shift's `start_time` falls before the existing shift's `end_time`. Shift windows are half-open, so adjacency is not a conflict: a new shift starting exactly when an existing one ends is allowed. A successful signup starts in `SIGNED_UP` with `hours_credited` 0 and raises the shift's `signed_up_count` by one.

The signup lifecycle then runs through organizer actions. Check-in moves `SIGNED_UP` → `CHECKED_IN` and immediately recomputes the volunteer's `projected_hours` and `projected_discount_pct`, because a checked-in-but-not-yet-completed shift counts toward the forward-looking projection. Check-out moves `CHECKED_IN` → `COMPLETED` (any other source state yields `ERR_SIGNUP_WRONG_STATE`), stamps the signup's `hours_credited` as the shift's duration in hours — the difference between the shift's `end_time` and `start_time`, in seconds, divided by 3600 — and recomputes the volunteer's `completed_hours`, `projected_hours`, and `projected_discount_pct`. Cancellation by the organizer or the owning volunteer moves `SIGNED_UP` → `CANCELLED` and decrements the shift's `signed_up_count`, freeing capacity. An organizer may also mark a `SIGNED_UP` signup as `NO_SHOW`, but only once the logical clock has passed the shift's `end_time`; an earlier attempt is rejected with `ERR_NO_SHOW_TOO_EARLY`. A no-show likewise decrements `signed_up_count`. Signups can be listed with `shift_id`, `volunteer_id`, and `status` filters.

Hours convert to discount through a tiered ladder with inclusive boundaries. A volunteer's `completed_hours` is the sum of `hours_credited` over their signups in `COMPLETED` status; their `projected_hours` adds, on top of that, the shift durations of their signups still in `CHECKED_IN`. The earned tier reads `completed_hours`: twelve hours or more earns a 20 percent discount; eight hours or more earns 15; four hours or more earns 10; anything less earns the 5 percent base. The volunteer's `projected_discount_pct` applies the same ladder to `projected_hours`, giving a forward-looking read model of what the volunteer is on track to hold. The distinction matters at pass issuance (§3.7): an issued pass pins the earned tier forever, while `projected_discount_pct` keeps moving as shifts are checked in and out.

### 3.7. Presale Passes

Presale access is credentialled. Once the event reaches `INTAKE_CLOSED` or `PRESALE_DAY`, the organizer triggers pass issuance for the whole event; attempting issuance in any other phase yields `ERR_EVENT_PHASE_MISMATCH`. Issuance walks all consignors and volunteers of the event in `created_at` ascending order and applies an explicit eligibility filter. A consignor earns a pass when their status is `ACTIVE` and at least one of their items sits in `ACCEPTED`, `ON_FLOOR`, `IN_CART`, or `SOLD`; the consignor pass carries a `discount_pct` of 0 — early access is the perk, not a price break. A volunteer earns a pass when at least one of their signups is in `CHECKED_IN` or `COMPLETED`, and their pass carries a `discount_pct` equal to the earned discount tier computed from `completed_hours` at the moment of issuance.

Each issued `PresalePass` records the event's `sale_event_id`, a `holder_type` of exactly `CONSIGNOR` or `VOLUNTEER`, and a polymorphic `holder_id` — the consignor's `id` when `holder_type` is `CONSIGNOR`, the volunteer's `id` when it is `VOLUNTEER`. Issuance is idempotent per holder: a holder who already has an `ACTIVE` pass for the event is skipped. Pinning is absolute: a pass's `discount_pct` never changes after issuance, no matter how many hours the volunteer later completes or forfeits. An organizer may revoke a pass, moving it `ACTIVE` → `REVOKED`; a revoked pass can no longer attach to new transactions, and any attempt to open a ticket with a pass that is not `ACTIVE` fails with `ERR_PASS_NOT_ACTIVE`. Passes can be listed with `sale_event_id`, `holder_id`, and `status` filters; a consignor or volunteer reading a single pass may read only passes they hold. The issuance call returns the passes created by that call as an array response — holders skipped as already issued are simply absent.

### 3.8. The Sales Floor: Tickets, Scans, Checkout, and Voids

A `Cashier` opens a sale ticket against a `sale_event_id`, and may attach a `presale_pass_id`. Opening is permitted only in `PRESALE_DAY` or `SALE_ACTIVE`. During `PRESALE_DAY` the pass is mandatory: opening a ticket without a valid `ACTIVE` pass is rejected with `ERR_PRESALE_PASS_REQUIRED` (HTTP 403), and a pass that has been revoked or is otherwise not `ACTIVE` fails with `ERR_PASS_NOT_ACTIVE`. At creation the server snapshots the pass's `discount_pct` into the transaction's `pass_discount_pct` — 0 when no pass is attached — so later revocation or reissuance can never rewrite an open ticket's economics. The ticket records the `cashier_id` from the cashier's `X-User-ID` purely as an opaque audit id, starts in `OPEN`, and carries `subtotal_cents`, `discount_cents`, `total_cents`, `tendered_cents`, and `change_cents`, all initially empty or zero.

Scanning is the heart of the floor. The cashier scans a `barcode` into an `OPEN` ticket — scanning into any other state fails with `ERR_TRANSACTION_NOT_OPEN`. The barcode must resolve to an item of the transaction's own event, or the scan is rejected with `ERR_BARCODE_NOT_FOUND`, and the item must currently be `ON_FLOOR`, or the scan fails with `ERR_ITEM_NOT_ON_FLOOR`. A successful scan moves the item `ON_FLOOR` → `IN_CART` and creates a `TransactionLine` that freezes the scan-time economics: the `transaction_id` and resolved `item_id`, a copy of the item's `barcode`, the `tag_price_cents` snapshot from the item's `price_cents`, the `markdown_pct_applied`, the `line_price_cents`, the `pass_discount_pct_applied`, and the `final_line_cents`.

Two discounts stack, in a fixed order. First the markdown: the `markdown_pct_applied` is the `discount_pct` of the event's markdown rule whose window contains the scan instant — `effective_from` inclusive, `effective_to` exclusive — and 0 when no rule matches or when the item's `discount_eligible` flag is false, regardless of any matching window. The `line_price_cents` is the tag price reduced by that percentage, rounded half-up to whole cents. Then the pass: the `pass_discount_pct_applied` snapshots the transaction's `pass_discount_pct` onto the line, and the `final_line_cents` is the `line_price_cents` reduced by that percentage, again rounded half-up to whole cents. Transaction totals obey the pinned rounding order of §2.6: `subtotal_cents` sums the current lines' `line_price_cents`, `total_cents` sums their `final_line_cents`, and `discount_cents` is the difference between the two — each line rounded first, then summed, never the reverse. Lines are audit-light rows carrying only `id` and `created_at`; they can be listed with `transaction_id` and `item_id` filters.

Removing a line — addressed by its `lineId` within the transaction — is the compensating twin of a scan: permitted while the ticket is `OPEN`, it deletes the line row, returns the item from `IN_CART` to `ON_FLOOR`, and recomputes the totals, leaving the sellable-inventory count unchanged; the response carries the removed line object.

Checkout completes the sale. It requires at least one current line — an empty ticket is rejected with `ERR_EMPTY_TRANSACTION` — and the tendered amount must cover the total: submitting `tendered_cents` below `total_cents` — or omitting it or sending a non-integer — fails with `ERR_INSUFFICIENT_TENDER` (HTTP 402). On success the ticket records `tendered_cents`, computes `change_cents` as the tendered amount minus the total, and moves `OPEN` → `COMPLETED`. Every line item then moves `IN_CART` → `SOLD` as the first cascade hop; each sale triggers recomputation of its consignor's `sold_count` and `sold_gross_cents` (the second hop, where `sold_gross_cents` sums `final_line_cents` over lines of the consignor's items in `COMPLETED` transactions) and recomputation of that consignor's `DRAFT` settlement provisional fields (the third hop); and the event's `sold_gross_cents` is recomputed to keep the money invariant of §2.10 exact.

Voids come in two strengths. While a ticket is still `OPEN`, either the cashier or the organizer may void it: every line item returns `IN_CART` → `ON_FLOOR` and the line rows are deleted. Voiding a `COMPLETED` transaction is an organizer-only compensation — a cashier attempting it is rejected with `ERR_FORBIDDEN` — and is permitted only in `PRESALE_DAY` or `SALE_ACTIVE`. The stronger void returns every line item `SOLD` → `ON_FLOOR`, decrements the consignors' sold counters and gross back down, recomputes the affected `DRAFT` settlements' provisional fields, recomputes the event's `sold_gross_cents`, and retains the line rows for audit. Checkout and completed-void form the compensating pair that conserves event gross. Voiding an already `VOIDED` transaction is rejected with `ERR_TRANSACTION_NOT_OPEN`. Transactions can be listed with `sale_event_id`, `presale_pass_id`, and `status` filters.

Finally, the floor gates settlement: advancing the event from `SALE_ACTIVE` to `SETTLEMENT` requires the clock to have reached `sale_end` and requires that no transaction of the event remain `OPEN`; lingering open tickets block the advance with `ERR_OPEN_TRANSACTIONS_REMAIN`. On this advance, every item still `ON_FLOOR` moves to `UNSOLD` in item `created_at` ascending order (hop 1), each triggering recomputation of its consignor's `unsold_count` and provisional counters (hop 2) and of the consignor's `DRAFT` settlement provisional fields — with the floor projection now removed (hop 3).

### 3.9. Settlement, Disputes, Payout, and Event Close

Settlement reconciles every consignor's proceeds. Once the event reaches `SALE_ACTIVE` or `SETTLEMENT`, the organizer regenerates settlements for the event: the server deletes every existing `DRAFT` settlement of the event and creates fresh `DRAFT` settlements for every consignor who has at least one item that was ever dropped off — that is, any item whose status is not `TAGGED`. Regeneration is legitimate to run repeatedly during those two phases, but two guards apply. If any settlement of the event has already reached `FINALIZED`, `DISPUTED`, or `PAID`, the regeneration is rejected with `ERR_SETTLEMENTS_LOCKED`. And because regeneration supersedes drafts built from sales data the client may not have seen, the request must carry `expected_sale_event_version` matching the event's current `version`; a stale value is rejected with `ERR_STALE_VERSION` (HTTP 412), as detailed in §2.9. The locked check outranks the stale-version check: a regeneration that is both locked and stale surfaces `ERR_SETTLEMENTS_LOCKED`. A successful regeneration increments the event's `version` by 1 and returns the newly created settlements as an array response.

Each `Settlement` names its `sale_event_id` and `consignor_id` and lives in one of four statuses: `DRAFT`, `FINALIZED`, `DISPUTED`, or `PAID`. While a settlement is in `DRAFT` and the event is in `SALE_ACTIVE` or `SETTLEMENT`, it maintains a forward-looking projection: `provisional_gross_cents` is the consignor's actual sold gross plus a sell-through projection that assumes half of the consignor's remaining `ON_FLOOR` inventory sells at today's markdown — for each such item, the line price at the current markdown is halved and rounded half-up to whole cents, and the per-item values are summed — and `provisional_payout_cents` runs the full payout pipeline on that estimated gross with the adjustment treated as 0. The settlement's `sold_item_count` tracks the consignor's items actually sold in `COMPLETED` transactions.

The payout pipeline itself runs in a pinned evaluation order, because its steps depend on one another in a way that admits no reordering. Step one computes `gross_cents`: the sum of `final_line_cents` over transaction lines whose item belongs to the consignor and whose transaction is `COMPLETED`. Step two reads the consignor split percentage from a three-tier ladder on that gross: below 20000 cents ($200.00) the consignor keeps 60 percent; from 20000 up to but not including 50000 cents ($500.00) they keep 65 percent; at 50000 cents or more they keep 70 percent. A volunteer bonus adds 5 percentage points when there exists a volunteer whose `linked_consignor_id` points at this consignor and whose `completed_hours` is at least 4, and the result is capped — the split is the smaller of the tiered-plus-bonus value and 75 percent. Step three computes `commission_cents`: the gross reduced by the consignor's split share, equivalently the gross multiplied by the house's remaining percentage, rounded half-up to whole cents. Step four sets `payout_before_fee_cents` to the gross minus the commission. Step five applies the supply fee: 1000 cents ($10.00), waived to 0 when `payout_before_fee_cents` is at least 30000 cents ($300.00) or when the volunteer-bonus condition of step two holds. The waiver test deliberately reads the pre-fee payout, never the post-fee payout; evaluating the fee first would produce different results. Step six computes `rejected_fee_cents` as 200 cents ($2.00) multiplied by the consignor's `rejected_count`. Step seven yields `payout_cents`: the pre-fee payout minus the supply fee, minus the rejected-item fee, plus `adjustment_cents`, floored at 0 so a payout can never go negative. The `adjustment_cents` field starts at 0 and accumulates dispute-resolution input.

Finalization freezes the final variant. An organizer finalizes a settlement only while the event is in `SETTLEMENT` and the settlement is in `DRAFT` — otherwise `ERR_SETTLEMENT_WRONG_STATE`. Finalization runs steps one through seven on actuals only, excluding any `ON_FLOOR` projection, and freezes the results onto the row: `gross_cents`, `split_pct`, `commission_cents`, `payout_before_fee_cents`, `supply_fee_cents`, `rejected_fee_cents`, and `payout_cents` transition from null to concrete values, and the settlement moves `DRAFT` → `FINALIZED`. Finalization also recomputes the two provisional fields one last time and retains them on the frozen row.

The dispute cycle gives consignors recourse. The owning consignor may dispute a `FINALIZED` settlement by supplying a `reason`; the settlement moves `FINALIZED` → `DISPUTED` and the reason is recorded in `dispute_reason`, overwriting any earlier one so it always reflects the latest dispute. The organizer resolves a `DISPUTED` settlement by submitting an `adjustment_cents` value, which is added onto the settlement's accumulated `adjustment_cents`, and the settlement cycles back to `DRAFT` so it can be re-finalized with the adjustment included. Resolution also resets the frozen final-variant fields (`gross_cents` through `payout_cents`) to null, retains the `dispute_reason`, and treats a missing or non-integer `adjustment_cents` as 0. Payment closes the loop: the organizer marks a `FINALIZED` settlement paid, but only once every item of the consignor sits in a terminal status — `SOLD`, `PICKED_UP`, or `DONATED` — otherwise the request fails with `ERR_ITEMS_NOT_TERMINAL`. Success moves `FINALIZED` → `PAID`. Settlements can be listed with `sale_event_id`, `consignor_id`, and `status` filters; a consignor reads only their own.

Wind-down returns or donates the leftovers. During `SETTLEMENT`, a consignor may pick up their own `UNSOLD` items provided the logical clock is at or before the event's `pickup_deadline`; a later attempt is rejected with `ERR_PICKUP_WINDOW_CLOSED`, and success moves the item `UNSOLD` → `PICKED_UP` and recomputes the consignor's `unsold_count`. Rejected items have a longer pickup window: a `REJECTED` item may be picked up in any phase from `INTAKE_CLOSED` through `SETTLEMENT`, moving `REJECTED` → `PICKED_UP` and recomputing `rejected_count`.

Closing the event is the final advance, `SETTLEMENT` → `CLOSED`. Before checking its preconditions, the advance performs a conditional donation cascade: every item still `UNSOLD` whose `donate_flag` is true moves to `DONATED` (recomputing the consignor's `unsold_count`), and every `REJECTED` item never picked up likewise moves to `DONATED` (recomputing `rejected_count`). Only then are the preconditions evaluated: every item of the event must sit in a terminal status — `SOLD`, `PICKED_UP`, or `DONATED` — with stragglers surfacing `ERR_ITEMS_NOT_TERMINAL`, and every settlement of the event must be `PAID` — a close attempted with any settlement not `PAID` is rejected with `ERR_EVENT_PHASE_MISMATCH` (HTTP 409). The event's `version` increments one last time, and `CLOSED` is terminal.

## 4. Endpoint Definitions

All endpoints live under the API root; every request carries the `X-User-ID` and `X-User-Role` headers described in §2.1. Creating a new resource returns 201 Created; operations that modify an existing resource, and all reads, return 200 OK. Request bodies, response payloads, side effects, and the full validation behavior of each operation are specified in Sections 2 and 3; this table is a routing and authorization summary only.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | /sale-events | Create a sale event (phase `DRAFT`) | EventOrganizer |
| GET | /sale-events | List sale events | EventOrganizer, Consignor, Volunteer, Inspector, Cashier |
| GET | /sale-events/{id} | Get one sale event | EventOrganizer, Consignor, Volunteer, Inspector, Cashier |
| POST | /sale-events/{id}/advance-phase | Advance the event phase to the exact next phase named in `to_phase` | EventOrganizer |
| POST | /sale-events/{id}/issue-presale-passes | Issue pinned-discount presale passes to all eligible consignors and volunteers; idempotent per holder | EventOrganizer |
| POST | /sale-events/{id}/generate-settlements | Create/supersede `DRAFT` settlements for every consignor with at least one item ever dropped off; OCC-guarded | EventOrganizer |
| POST | /markdown-rules | Create a markdown window; no half-open overlap per event | EventOrganizer |
| GET | /markdown-rules | List markdown rules | EventOrganizer, Cashier |
| GET | /markdown-rules/{id} | Get one markdown rule | EventOrganizer, Cashier |
| POST | /consignors | Self-register a consignor for an event; assigns `consignor_code` | Anonymous |
| GET | /consignors | List consignors | EventOrganizer |
| GET | /consignors/{id} | Get one consignor (owner or organizer) | EventOrganizer, Consignor |
| POST | /consignors/{id}/withdraw | Withdraw a consignor; requires zero items | EventOrganizer, Consignor |
| POST | /volunteers | Self-register a volunteer; optional `linked_consignor_id` | Anonymous |
| GET | /volunteers | List volunteers | EventOrganizer |
| GET | /volunteers/{id} | Get one volunteer (self or organizer) | EventOrganizer, Volunteer, Inspector |
| POST | /drop-off-slots | Create a drop-off appointment slot | EventOrganizer |
| GET | /drop-off-slots | List slots with `booked_count` | EventOrganizer, Consignor |
| GET | /drop-off-slots/{id} | Get one slot | EventOrganizer, Consignor |
| POST | /drop-off-bookings | Book a slot (aggregate capacity); one active booking per consignor | Consignor |
| GET | /drop-off-bookings | List bookings | EventOrganizer, Consignor |
| GET | /drop-off-bookings/{id} | Get one booking | EventOrganizer, Consignor |
| POST | /drop-off-bookings/{id}/cancel | Cancel a `BOOKED` booking; frees capacity | EventOrganizer, Consignor |
| POST | /drop-off-bookings/{id}/check-in | Check in a booking at the venue | EventOrganizer |
| POST | /items | Tag a new item; server assigns `barcode` | Consignor |
| GET | /items | List items with filters | EventOrganizer, Consignor, Cashier, Inspector |
| GET | /items/{id} | Get one item | EventOrganizer, Consignor, Cashier, Inspector |
| POST | /items/{id}/drop-off | Drop off a `TAGGED` item during intake with a checked-in booking | Consignor |
| POST | /items/{id}/inspect | Inspect a `DROPPED_OFF` item; creates an `InspectionRecord` | Inspector |
| POST | /items/{id}/pickup | Pick up a `REJECTED` or `UNSOLD` item | Consignor |
| GET | /inspection-records | List inspection audit records | EventOrganizer, Inspector |
| GET | /inspection-records/{id} | Get one inspection record | EventOrganizer, Inspector |
| POST | /volunteer-shifts | Create a volunteer shift | EventOrganizer |
| GET | /volunteer-shifts | List shifts | EventOrganizer, Volunteer, Inspector |
| GET | /volunteer-shifts/{id} | Get one shift | EventOrganizer, Volunteer, Inspector |
| POST | /shift-signups | Sign up for a shift; half-open overlap and capacity enforced | Volunteer |
| GET | /shift-signups | List signups | EventOrganizer, Volunteer, Inspector |
| GET | /shift-signups/{id} | Get one signup | EventOrganizer, Volunteer, Inspector |
| POST | /shift-signups/{id}/cancel | Cancel a `SIGNED_UP` signup | EventOrganizer, Volunteer |
| POST | /shift-signups/{id}/check-in | Check in a signup | EventOrganizer |
| POST | /shift-signups/{id}/check-out | Complete a checked-in signup; credits hours | EventOrganizer |
| POST | /shift-signups/{id}/mark-no-show | Mark a `SIGNED_UP` signup no-show after shift end | EventOrganizer |
| GET | /presale-passes | List presale passes | EventOrganizer, Consignor, Volunteer, Cashier |
| GET | /presale-passes/{id} | Get one presale pass | EventOrganizer, Consignor, Volunteer, Cashier |
| POST | /presale-passes/{id}/revoke | Revoke a pass | EventOrganizer |
| POST | /pos-transactions | Open a sale ticket; pass mandatory during presale and snapshotted | Cashier |
| GET | /pos-transactions | List transactions | EventOrganizer, Cashier |
| GET | /pos-transactions/{id} | Get one transaction | EventOrganizer, Cashier |
| POST | /pos-transactions/{id}/lines | Scan a barcode into an `OPEN` transaction; computes scan-time prices | Cashier |
| GET | /transaction-lines | List transaction lines | EventOrganizer, Cashier |
| GET | /transaction-lines/{id} | Get one transaction line | EventOrganizer, Cashier |
| DELETE | /pos-transactions/{id}/lines/{lineId} | Remove a line from an `OPEN` transaction; item returns to `ON_FLOOR` | Cashier |
| POST | /pos-transactions/{id}/checkout | Complete an `OPEN` transaction; items move to `SOLD` with full cascade | Cashier |
| POST | /pos-transactions/{id}/void | Void a transaction; Cashier only while `OPEN`, EventOrganizer also when `COMPLETED` | Cashier, EventOrganizer |
| GET | /settlements | List settlements | EventOrganizer, Consignor |
| GET | /settlements/{id} | Get one settlement (owner or organizer) | EventOrganizer, Consignor |
| POST | /settlements/{id}/finalize | Freeze the final-variant payout | EventOrganizer |
| POST | /settlements/{id}/dispute | Consignor disputes a `FINALIZED` settlement | Consignor |
| POST | /settlements/{id}/resolve | Resolve a dispute; accumulates `adjustment_cents` and returns to `DRAFT` | EventOrganizer |
| POST | /settlements/{id}/mark-paid | Pay a `FINALIZED` settlement; all consignor items must be terminal | EventOrganizer |
| POST | /_clock/set_current_utc | Set the server's logical clock (ISO 8601 UTC); startup default is exactly 2026-05-01T00:00:00Z | EventOrganizer |

## 5. Error Code Catalogue

The following table enumerates every error identifier and its HTTP status. The conditions that trigger each error are specified in the narratives of Sections 2 and 3.

| Error ID | HTTP Status Code |
|---|---|
| ERR_MISSING_OR_INVALID_USER_CONTEXT | 400 |
| ERR_FORBIDDEN | 403 |
| ERR_SALE_EVENT_NOT_FOUND | 404 |
| ERR_CONSIGNOR_NOT_FOUND | 404 |
| ERR_ITEM_NOT_FOUND | 404 |
| ERR_SLOT_NOT_FOUND | 404 |
| ERR_BOOKING_NOT_FOUND | 404 |
| ERR_VOLUNTEER_NOT_FOUND | 404 |
| ERR_SHIFT_NOT_FOUND | 404 |
| ERR_SIGNUP_NOT_FOUND | 404 |
| ERR_PASS_NOT_FOUND | 404 |
| ERR_TRANSACTION_NOT_FOUND | 404 |
| ERR_LINE_NOT_FOUND | 404 |
| ERR_SETTLEMENT_NOT_FOUND | 404 |
| ERR_MARKDOWN_RULE_NOT_FOUND | 404 |
| ERR_BARCODE_NOT_FOUND | 404 |
| ERR_INSPECTION_RECORD_NOT_FOUND | 404 |
| ERR_EVENT_PHASE_MISMATCH | 409 |
| ERR_ITEM_WRONG_STATE | 409 |
| ERR_TRANSACTION_NOT_OPEN | 409 |
| ERR_BOOKING_WRONG_STATE | 409 |
| ERR_SIGNUP_WRONG_STATE | 409 |
| ERR_SETTLEMENT_WRONG_STATE | 409 |
| ERR_SETTLEMENTS_LOCKED | 409 |
| ERR_PASS_NOT_ACTIVE | 409 |
| ERR_INSPECTION_SELF_DEALING | 403 |
| ERR_INTAKE_WINDOW_CLOSED | 409 |
| ERR_INSPECTION_DEADLINE_PASSED | 409 |
| ERR_PICKUP_WINDOW_CLOSED | 409 |
| ERR_SHIFT_OVERLAP | 409 |
| ERR_INVALID_TIME_WINDOW | 409 |
| ERR_MARKDOWN_WINDOW_OVERLAP | 409 |
| ERR_NO_SHOW_TOO_EARLY | 409 |
| ERR_SLOT_FULL | 409 |
| ERR_SHIFT_FULL | 409 |
| ERR_DUPLICATE_ACTIVE_BOOKING | 409 |
| ERR_PRICE_BELOW_MINIMUM | 400 |
| ERR_PRICE_INCREMENT_VIOLATION | 400 |
| ERR_ITEM_NOT_ON_FLOOR | 409 |
| ERR_PRESALE_PASS_REQUIRED | 403 |
| ERR_NO_CHECKED_IN_BOOKING | 409 |
| ERR_UNINSPECTED_ITEMS_REMAIN | 409 |
| ERR_OPEN_TRANSACTIONS_REMAIN | 409 |
| ERR_ITEMS_NOT_TERMINAL | 409 |
| ERR_CONSIGNOR_HAS_ITEMS | 409 |
| ERR_EMPTY_TRANSACTION | 409 |
| ERR_STALE_VERSION | 412 |
| ERR_INSUFFICIENT_TENDER | 402 |
| ERR_VALIDATION | 400 |
| ERR_NOT_FOUND | 404 |
| ERR_METHOD_NOT_ALLOWED | 405 |
| ERR_INTERNAL | 500 |
