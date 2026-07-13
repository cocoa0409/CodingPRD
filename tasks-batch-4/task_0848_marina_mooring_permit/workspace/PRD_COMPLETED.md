# Marina Mooring Permit API — Product Requirements Document

## 1. Introduction

Coastal municipalities operate their public marinas as a scarce, seasonally-contested public resource: there are only so many slips and moorings, far more boaters want them than can be accommodated, and the town must reconcile fairness, safety, environmental compliance, and cost recovery all at once. This document specifies the Marina Mooring Permit API, the system of record that governs the full lifecycle of a berth — from the moment a marina and its inventory of slips and moorings are configured, through the competition for space by direct offer, waitlist promotion, and seasonal lottery, to the day-to-day realities of vessel registration, pump-out compliance, liveaboard limits, derelict-vessel enforcement, and billing.

The API serves three constituencies with distinct authority. A harbormaster runs marina operations: creating inventory, adjudicating waitlists and lotteries, enforcing registration and derelict rules, and reassigning or revoking permits. A finance clerk owns the money: taking payments and waiving charges. Boaters themselves self-serve — registering vessels, applying for permits, entering lotteries, buying launch-ramp passes, and paying their own invoices. Because so many of these processes turn on the passage of time (seasons open and close, registrations expire, offers and lottery claims lapse, pump-outs come due), the system runs against a single logical clock that operators advance explicitly, and a maintenance sweep translates the clock's advance into the corresponding state changes.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and cross-cutting principles that apply across every endpoint.

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. The role must be exactly one of `Harbormaster`, `FinanceClerk`, or `Boater`. A request that is missing the role header or carries an unrecognized value is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A syntactically valid role that is not permitted to perform the requested operation is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

The three roles differ in how `X-User-ID` binds to data. When `X-User-Role` is `Harbormaster`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it (for example the acting role is captured on a pump-out record's `recorded_by_role`) but never compares it to any entity's `id`. When `X-User-Role` is `FinanceClerk`, `X-User-ID` is likewise an opaque operator identifier with no entity backing. When `X-User-Role` is `Boater`, `X-User-ID` is the `id` of the acting `Boater`; ownership checks on any resource that references a boater compare that resource's owning boater to `X-User-ID`. Concretely, a `Boater` may act only on resources they own — a permit whose `boater_id` is theirs, a vessel whose `boater_id` is theirs, an invoice whose `boater_id` is theirs, a lottery entry whose `boater_id` is theirs, or a ramp pass whose `boater_id` is theirs. When a `Boater` attempts a mutation on a resource that resolves to a different owner, the request is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403).

The `Harbormaster` is the marina operations authority and is the only role permitted to create marinas, berths, and boater accounts; to run the maintenance sweep; to revoke, transfer, or reassign permits; to open lottery rounds and draw them; to file, serve notice on, and close derelict reports; to revoke ramp passes; and to advance the logical clock. The `FinanceClerk` is the billing authority and is the only role permitted to waive an invoice. Paying an invoice, registering a vessel, applying for a permit, cancelling a permit, entering and claiming a lottery, buying a ramp pass, and logging a pump-out are shared operations that a `Harbormaster` may perform on any resource and a `Boater` may perform on their own. All GET reads are available to every role, subject to the boater ownership rule for non-public resources.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, may not be smaller than 1, and may not exceed 100. The `offset` parameter is the number of items to skip and defaults to 0, with a minimum of 0. A `limit` outside 1 through 100, or a negative `offset`, is rejected with `ERR_PAGINATION_INVALID` (HTTP 400).

Unless a specific endpoint states otherwise, list endpoints return resources sorted by their `created_at` timestamp in ascending order. Every list response includes `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope; `has_more` is true exactly when `offset` plus `limit` is strictly less than `total_count`.

### 2.4. Common Resource Properties and the Logical Clock

Every top-level resource carries a server-minted `id` formatted as a UUID (with no type prefix) and a `created_at` timestamp in ISO 8601 UTC with three fractional digits. Most resources — marinas, berths, boaters, vessels, permits, derelict reports, ramp passes, lottery rounds, lottery entries, and invoices — additionally carry an `updated_at` timestamp (ISO 8601 UTC, three fractional digits) that is refreshed on every mutation, and a `version` integer that starts at its initial value and increments by one on every mutation. The one exception is the pump-out record: it is immutable once written and therefore carries only `id` and `created_at`; it has neither an `updated_at` nor a `version` field. Whenever the system recomputes a derived field on a resource (for example a marina's occupancy counters), that recomputation counts as a mutation of the resource: its `updated_at` is refreshed and its `version` is incremented.

All time-dependent behavior in the system is evaluated against a single logical clock rather than wall-clock time. At server startup the clock reads exactly `2026-03-01T00:00:00Z` and never falls back to real time; an operator may move it to any instant by supplying a `to_iso8601` value to the clock-set capability. Setting the clock only changes the reference instant used for date comparisons — registration expiry, season boundaries, pump-out intervals, offer and claim deadlines, and lottery windows — and does not itself run any maintenance sweep.

### 2.5. Monetary Precision and Fee Rounding

All monetary amounts are stored and returned as integer cents. Wherever a calculation multiplies by a rate or a proration factor and a fractional cent results, the value is rounded half up to the nearest whole cent. Proration is applied per component: each component of a prorated fee is rounded to whole cents on its own and only then are the rounded components summed — the system never prorates a single combined gross figure. This per-component discipline is a deliberate contract, because rounding each part separately and rounding the whole can differ by a cent.

### 2.6. Optimistic Concurrency Control on Berth Reassignment

Reassigning a permit to a different berth is guarded by optimistic concurrency control on the permit. The reassignment request must carry `expected_permit_version`, holding the `version` of the target permit that the client last observed. The server compares that value against the permit's current `version`; if another writer has advanced the permit's `version` since the client last read it, the reassignment is rejected with `ERR_STALE_VERSION` (HTTP 412). Because a reassignment is always legitimate on an active permit — the permit stays `ACTIVE` and no gating state field changes — this stale-version check is the sole guard against a caller acting on an out-of-date view of which berth the permit holds; a request whose `expected_permit_version` no longer matches is refused even though nothing else about the operation is invalid. No other endpoint accepts or requires a version field.

### 2.7. Berth Inventory and Occupancy Counters

A marina continuously reports the state of its inventory through six computed counters, each recomputed whenever a berth changes status or a permit is activated, expires, is revoked, or is transferred. The `available_slip_count` is the number of berths whose `berth_type` is `SLIP` and whose `status` is `AVAILABLE`; the `occupied_slip_count` is the number of `SLIP` berths whose `status` is `OCCUPIED`. Symmetrically, `available_mooring_count` and `occupied_mooring_count` count `MOORING` berths in `AVAILABLE` and `OCCUPIED` status respectively. The `liveaboard_count` is the number of permits for the marina that are in `ACTIVE` status with `is_liveaboard` set to true, and `waitlist_length` is the number of permits for the marina in `WAITLISTED` status. As an invariant, the count of occupied slips always equals the number of `ACTIVE` or `SUSPENDED` permits holding slip berths, since a suspended permit continues to occupy its berth.

Berth status changes propagate as cascades. When a permit releases a berth, that berth returns toward the `AVAILABLE` pool and its `current_permit_id` is cleared; a freed berth then triggers waitlist promotion, which may immediately re-reserve the berth for the next ranked applicant. Each such propagation independently mutates the affected marina, berth, and permit resources — refreshing their `updated_at` and incrementing their `version` — so that the reported counters and the underlying rows never drift apart.

### 2.8. Nested Resource Retrieval and Reference Resolution

Several endpoints address a resource nested under another (for example a vessel's pump-out records) or reference resources by identifier in the request body. The system validates every path and body reference — `marina_id`, `boater_id`, `vessel_id`, `berth_id`, `round_id`, `invoice_id`, `permit_id`, and the like — in left-to-right order, and rejects the request with `ERR_NOT_FOUND` (HTTP 404) at the first identifier that does not resolve to an existing resource. Existence is checked before any state or business rule is evaluated, so a reference to a missing parent surfaces as a not-found error rather than a downstream conflict.

### 2.9. Validation Ordering and Precedence

When several checks could fail on the same request, they are evaluated in a fixed order of precedence so that the returned error is deterministic. Authentication comes first: a missing or invalid role yields `ERR_UNAUTHENTICATED`. Authorization is second: a role not permitted for the operation yields `ERR_UNAUTHORIZED`. Third, existence of every referenced resource is checked, yielding `ERR_NOT_FOUND`. Fourth, for a `Boater`-initiated mutation, ownership of the target resource is checked, yielding `ERR_NOT_RESOURCE_OWNER`. Fifth, the target resource's state is checked against the state machine for the requested transition, yielding `ERR_INVALID_STATE` (HTTP 409) when the resource is not in a legal from-state. Only after these five gates do the domain-specific business rules run — registration currency, berth-type and size matching, season overlap, ramp-pass overlap, vessel length, the liveaboard cap, payment amount, lottery timing, and the reassignment stale-version check — each described alongside the workflow it guards. Malformed bodies, missing required fields, and invalid enum values are rejected with `ERR_VALIDATION` (HTTP 400).

## 3. Business Logic & Workflows

### 3.1. Configuring a Marina and Its Berth Inventory

A harbormaster stands up a marina by supplying a `name`, the inclusive operating-season boundaries `season_start_date` and `season_end_date`, a `liveaboard_cap` giving the maximum number of `ACTIVE` liveaboard permits allowed at once, and optionally a `pumpout_interval_days` value; when the interval is omitted it defaults to 30 days. The `liveaboard_cap` must be zero or greater — a negative cap is rejected with `ERR_LIVEABOARD_CAP_NEGATIVE` (HTTP 400) — and the season must be well-formed, so a `season_end_date` earlier than `season_start_date` is rejected with `ERR_INVALID_DATE_RANGE` (HTTP 400). A newly created marina begins with all six occupancy counters at zero.

Into that marina the harbormaster adds berths, each created with its owning `marina_id`, a `berth_type` of either `SLIP` or `MOORING`, a `size_class` of `SMALL`, `MEDIUM`, or `LARGE`, and a `max_length_ft` giving the longest vessel the berth accepts. A berth may optionally be flagged `resident_only`, which defaults to false; when true, only a resident boater may be permitted there. Every berth is born `AVAILABLE`. Over its life a berth moves among `AVAILABLE`, `RESERVED`, `OCCUPIED`, and `OUT_OF_SERVICE`: it becomes `RESERVED` when a permit is offered it, advances to `OCCUPIED` when that permit activates, and returns to `AVAILABLE` when the offer is declined or expires or when the occupying permit ends. While a berth is `RESERVED` or `OCCUPIED` its `current_permit_id` names the permit holding it; while `AVAILABLE` or `OUT_OF_SERVICE` that pointer is null. Berths, boaters, and vessels can all be listed and filtered — berths by `marina_id`, `berth_type`, and `status`; the catalog of marinas and berths is public reading for every role.

### 3.2. Boater Accounts and Vessel Registration

A boater account is registered with a `full_name`, an `email`, a `residency_status` of either `RESIDENT` or `NON_RESIDENT`, and an optional `street_address`. Every account is created in `ACTIVE` state; `account_status` has no other value in this version and no suspension path is exposed. Residency is consequential: it drives both the fee a boater pays and their ranking in waitlists and lotteries.

Under a boater, vessels are registered with the owning `boater_id`, a `name`, a `length_ft` in whole feet, a `registration_number`, a `registration_expiry_date`, and a `has_holding_tank` flag indicating whether the vessel carries a marine sanitation holding tank subject to pump-out rules. Two vessel attributes are computed rather than supplied. The `registration_status` is `REGISTERED` while the logical clock is on or before `registration_expiry_date` and the vessel has not been impounded, becomes `EXPIRED` once the clock is strictly after `registration_expiry_date`, and becomes `REVOKED` after a derelict impound. The `pumpout_status` is `NA` when the vessel has no holding tank; otherwise it is `OVERDUE` when the number of whole days since the vessel's last pump-out is strictly greater than the applicable `pumpout_interval_days` — taken from the marina of the vessel's governing permit, where the governing permit is an `ACTIVE` or `SUSPENDED` permit for the vessel if one exists and otherwise the vessel's most recently created permit, and defaulting to 30 days when the vessel has no permit at all — and `COMPLIANT` when it is at or below that interval. The reference point for that day count is the vessel's `last_pumpout_date` — the date of its most recent pump-out record, or null when none exists — and when there is no prior pump-out the count runs from that governing permit's `activated_on_date` if available, or else from the vessel's creation. Vessels can be listed and filtered by `boater_id` and `registration_status`.

### 3.3. Applying for a Permit: Immediate Offer or Waitlist

A boater (or a harbormaster acting for one) applies for a seasonal permit by supplying the target `marina_id`, the applicant `boater_id`, the `vessel_id`, the `requested_berth_type`, the `requested_size_class`, and the `season_year`. The applicant's vessel must be currently `REGISTERED`; an application on an `EXPIRED` or `REVOKED` vessel is rejected with `ERR_VESSEL_REGISTRATION_EXPIRED` (HTTP 422). At creation the system copies the marina's season boundaries onto the permit as its own `season_start_date` and `season_end_date`, records how the permit was created in `source` (`DIRECT`, `WAITLIST`, `LOTTERY`, or `TRANSFER`), and derives two fields from the boater: `fee_basis` copies the boater's residency (`RESIDENT` or `NON_RESIDENT`), and `priority_tier` is 0 for a resident and 1 for a non-resident, where the lower number ranks ahead.

Whether the permit is offered immediately or waitlisted depends on inventory. If a berth exists in the marina whose `berth_type` equals the `requested_berth_type`, whose `size_class` equals the `requested_size_class`, whose `status` is `AVAILABLE`, whose `max_length_ft` is at least the vessel's `length_ft`, and which is either not `resident_only` or is being taken by a resident, the applicant is immediately assignable and the permit is created `OFFERED`. Offering reserves that berth: the permit's `berth_id` is set, the berth moves from `AVAILABLE` to `RESERVED`, and its `current_permit_id` points at the new permit. The provisional full-season fee is computed and stored in `provisional_fee_cents`, a `PERMIT` invoice for that amount is issued `UNPAID` with its identifier recorded in `invoice_id`, and `offer_expires_at` is set to seven days after the current clock, the offer's payment deadline. On the immediate-offer path the vessel must fit the berth: a `length_ft` greater than the berth's `max_length_ft` is rejected with `ERR_VESSEL_TOO_LONG` (HTTP 422), and a requested berth type or size class that cannot be matched, or a `resident_only` berth requested by a non-resident, is rejected with `ERR_BERTH_TYPE_MISMATCH` (HTTP 422).

If no such berth is free at creation, the permit is instead created `WAITLISTED` with a null `berth_id`, and the marina's `waitlist_length` rises by one. A waitlisted permit carries no invoice yet. The applicant may withdraw a `WAITLISTED` permit, which moves it to the terminal `CANCELLED` state and lowers `waitlist_length` by one. Permits can be listed and filtered by `marina_id`, `boater_id`, `vessel_id`, `berth_id`, and `status`.

### 3.4. Billing, Payment, Activation, and Fee Reconciliation

Every chargeable event produces an invoice billed to a `boater_id`, stamped with an `invoice_type` of `PERMIT`, `RAMP_PASS`, `DERELICT`, or `TRANSFER` and a polymorphic `reference_id` that — read together with the type — points at the permit, ramp pass, or derelict report being billed. An invoice records the `amount_due_cents` charged at issue, the cumulative `amount_paid_cents` and `amount_refunded_cents`, a `due_date`, and a `status` that begins `UNPAID` and can become `PAID`, `PARTIALLY_REFUNDED`, `REFUNDED`, `VOID`, or `WAIVED`. Invoices can be listed and filtered by `boater_id`, `status`, and `invoice_type`.

Payment is all-or-nothing. Paying an invoice supplies an `amount_cents` that must exactly equal the invoice's `amount_due_cents`; a mismatched amount is rejected with `ERR_PAYMENT_AMOUNT_MISMATCH` (HTTP 422), and an invoice that is not `UNPAID` cannot be paid and is rejected with `ERR_INVOICE_NOT_PAYABLE` (HTTP 409). A successful payment sets `amount_paid_cents` equal to `amount_due_cents` and moves the invoice to `PAID`. When the paid invoice is a `PERMIT` invoice, its permit transitions from `OFFERED` to `ACTIVE`. A finance clerk may alternatively waive an `UNPAID` invoice, moving it to `WAIVED`; waiving a `PERMIT` invoice likewise activates its permit, the fee being treated as satisfied.

Activation is where the season fee is settled. Before an offered permit becomes `ACTIVE`, its berth must still be `RESERVED` for it, its vessel must still be `REGISTERED`, and there must be no season overlap on that berth: among the `ACTIVE`, `OFFERED`, and `SUSPENDED` permits on the berth, the half-open season intervals — running from `season_start_date` up to but not including `season_end_date` — must not overlap, with exact adjacency permitted; an overlap is rejected with `ERR_BERTH_SEASON_CONFLICT` (HTTP 409). If the permit is a liveaboard permit, activation additionally requires that the marina's `liveaboard_count` be strictly below its `liveaboard_cap`; when the count has already reached the cap the activation is rejected with `ERR_LIVEABOARD_LIMIT_REACHED` (HTTP 422). On success the berth moves from `RESERVED` to `OCCUPIED`, `activated_on_date` is set to the current clock and `offer_expires_at` is cleared, the marina's occupied-slip or occupied-mooring counter rises by one, and — if the permit is a liveaboard — `liveaboard_count` rises by one.

At activation the fee is recomputed on a prorated basis and stored in `final_fee_cents` (null until then). The provisional fee is the full-season charge. Its length component is the per-foot rate for the requested berth type — 4,000 cents per foot for a `SLIP`, 2,500 cents per foot for a `MOORING` — multiplied by the vessel's `length_ft` rounded up to a whole foot; that length component is then multiplied by the residency multiplier, which is 1.00 for a resident and 1.75 for a non-resident, and the product is rounded half up to whole cents to give the scaled length charge. If the permit is a liveaboard, a flat surcharge of 50,000 cents is added; the sum of the scaled length charge and the liveaboard surcharge is the provisional fee. The final fee prorates by the share of the season remaining at activation. The season length in days is the number of days from `season_start_date` to `season_end_date` plus one (inclusive of both endpoints), and the remaining days is the number of days from `activated_on_date` to `season_end_date` plus one. Each component is prorated and rounded on its own: the scaled length charge multiplied by remaining days divided by season days, rounded half up to whole cents, plus the liveaboard surcharge multiplied by remaining days divided by season days, rounded half up to whole cents. The final fee is the sum of those two separately-rounded components — never the rounding of a single combined gross figure. Whenever the resulting final fee is below the provisional fee the difference is refunded on the invoice: `amount_refunded_cents` rises by the positive difference between `provisional_fee_cents` and `final_fee_cents`, and the invoice becomes `PARTIALLY_REFUNDED`, or fully `REFUNDED` when the refund equals the amount paid.

### 3.5. Berth Release, Waitlist Promotion, Revocation, Transfer, and Reassignment

Berths free up through several paths, and every freeing runs the same promotion logic. When a boater declines an `OFFERED` permit, the permit moves to the terminal `DECLINED` state, its reserved berth returns from `RESERVED` to `AVAILABLE` with `current_permit_id` cleared, and its `PERMIT` invoice is voided. When an offer's payment deadline lapses — the clock passing `offer_expires_at` — the maintenance sweep moves the permit to `DECLINED` with the same berth release and invoice void. When an `ACTIVE` or `SUSPENDED` permit reaches the end of its season — the clock passing `season_end_date` — the sweep expires it to `EXPIRED`, returning the berth from `OCCUPIED` to `AVAILABLE`, decrementing occupancy, and decrementing `liveaboard_count` if it was a liveaboard. A harbormaster may revoke an `ACTIVE` or `SUSPENDED` permit outright, optionally recording a `reason`; revocation moves the permit to `REVOKED`, computes a refund, releases the berth, and decrements occupancy and any liveaboard count. In each of these cases the freed berth immediately triggers waitlist promotion.

Waitlist promotion selects, among the `WAITLISTED` permits at the marina whose `requested_berth_type` and `requested_size_class` match the freed berth, whose vessel `length_ft` is at most the berth's `max_length_ft`, and which qualify for the berth (the berth is not `resident_only`, or the permit's `fee_basis` is `RESIDENT`), the single winner ranked first by lowest `priority_tier` and, among equal tiers, by earliest `created_at` — resident applicants ahead of non-residents, and earlier applicants ahead of later ones, with the tie broken by creation time and never by identifier. The winning permit moves from `WAITLISTED` to `OFFERED`: it is assigned the freed berth, the berth moves to `RESERVED`, its provisional fee is computed and a `PERMIT` invoice issued `UNPAID`, `offer_expires_at` is set, and `waitlist_length` falls by one. If no eligible permit exists, the berth simply stays `AVAILABLE`.

A revoke refund returns the unused portion of what was actually paid. The season length is again the days from `season_start_date` to `season_end_date` plus one; the remaining days is the days from the current clock to `season_end_date` plus one, but never less than zero. The net amount paid is `amount_paid_cents` minus `amount_refunded_cents`, and the refund is that net amount multiplied by remaining days divided by season days, rounded half up to whole cents. The refund is added to the invoice's `amount_refunded_cents`, moving it to `PARTIALLY_REFUNDED` when the refund is greater than zero and less than the net paid, or to `REFUNDED` when the refund equals the net paid.

A harbormaster may transfer an `ACTIVE` permit to another boater by supplying `to_boater_id`, which must exist and differ from the permit's current `boater_id`; a target equal to the current holder is rejected with `ERR_TRANSFER_TARGET_INVALID` (HTTP 422). Transfer moves the original permit to the terminal `TRANSFERRED` state and creates a new `ACTIVE` permit for the target boater on the same `berth_id`, same vessel, and same season dates, with `source` `TRANSFER`. A new `TRANSFER` invoice for a flat 5,000 cents is issued to the target boater, the berth's `current_permit_id` is repointed to the new permit, and because the boat has not moved the occupancy and liveaboard counts are unchanged.

A harbormaster may also reassign an `ACTIVE` permit to a different `AVAILABLE` berth by supplying the `new_berth_id` and the concurrency token `expected_permit_version`. Beyond the stale-version guard, the target berth must be `AVAILABLE` — otherwise `ERR_BERTH_NOT_AVAILABLE` (HTTP 409) — the vessel must fit the new berth's `max_length_ft` (else `ERR_VESSEL_TOO_LONG`), the new berth's type and size must match and honor its `resident_only` flag (else `ERR_BERTH_TYPE_MISMATCH`), and the move must not create a season overlap on the new berth (else `ERR_BERTH_SEASON_CONFLICT`). On success the old berth moves from `OCCUPIED` to `AVAILABLE`, triggering waitlist promotion on that vacated berth, the new berth moves from `AVAILABLE` to `OCCUPIED`, and the permit's `version` increments by one. Revocation, transfer, and reassignment all require the permit to be in the appropriate `ACTIVE` or `SUSPENDED` posture; attempting them on a permit that is not in the required state is rejected with `ERR_PERMIT_NOT_ACTIVE` (HTTP 409).

### 3.6. The Seasonal Lottery

For berths allocated by lottery rather than first-come offer, a harbormaster opens a lottery round bound to a `marina_id`, a `season_year`, a `berth_type`, an `entry_open_date` and `entry_close_date` bracketing the entry window (both inclusive), and an ordered `berth_ids` list naming the berths this round awards in the order winners will take them. The `entry_close_date` may not precede the `entry_open_date`, or the round is rejected with `ERR_INVALID_DATE_RANGE`. A round begins `OPEN`, later becomes `DRAWN`, and finally `CLOSED`. Rounds can be listed and filtered by `marina_id` and `status`.

While a round is `OPEN` and the clock lies within its entry window, a boater enters by supplying the `round_id`, their `boater_id`, and a `vessel_id`; the vessel must be `REGISTERED` or the entry is rejected with `ERR_VESSEL_REGISTRATION_EXPIRED`. Each entry receives a `draw_number` — a sequential 1-based ordinal assigned within the round by `created_at` ascending, a deterministic ordering input that is never random — and a `priority_tier` copied from the boater (0 resident, 1 non-resident). An entry begins `ENTERED`. The same boater-and-vessel pair may not enter the same round twice; a duplicate is rejected with `ERR_DUPLICATE_LOTTERY_ENTRY` (HTTP 409). An entry attempted when the round is not `OPEN`, or when the clock lies outside the entry window, is rejected with `ERR_ENTRY_WINDOW_CLOSED` (HTTP 409).

A harbormaster draws the round once the clock is strictly after the `entry_close_date`; a premature draw is rejected with `ERR_ROUND_NOT_CLOSED_FOR_DRAW` (HTTP 409), and a draw on a round not in `OPEN` status is rejected with `ERR_ROUND_ALREADY_DRAWN` (HTTP 409). The draw considers only `ENTERED` entries whose vessel is `REGISTERED` at the moment of the draw, ranks them by lowest `priority_tier` and then by lowest `draw_number`, and awards berths as a waterfall: with K equal to the number of ids in `berth_ids`, the first K ranked entries move from `ENTERED` to `WON`, the i-th winner receiving the i-th berth id as its `awarded_berth_id`; all remaining eligible entries and any entry whose vessel was not `REGISTERED` move from `ENTERED` to the terminal `LOST` state. Each winner's `claim_deadline` is set to fourteen days after the draw, and the round's `drawn_on_date` is stamped; no `PERMIT` invoice is issued until a winner claims. If no entry is eligible, there are no winners, everyone remaining moves to `LOST`, and the berths stay `AVAILABLE`.

A winner claims a `WON` entry, optionally declaring `is_liveaboard`, provided the clock is at or before the `claim_deadline` and the awarded berth is still `AVAILABLE`; a claim after the deadline is rejected with `ERR_CLAIM_DEADLINE_PASSED` (HTTP 409), a claim on an entry not in `WON` status with `ERR_ENTRY_NOT_WON` (HTTP 409), and an awarded berth no longer available with `ERR_BERTH_NOT_AVAILABLE`. Claiming moves the entry to the terminal `CLAIMED` state and creates a permit on the awarded berth with `source` `LOTTERY` in `OFFERED` status: the provisional fee is computed, a `PERMIT` invoice is issued, the entry's `permit_id` is recorded, and the berth moves from `AVAILABLE` to `RESERVED`. A winner who lets the deadline pass is swept to the terminal `FORFEITED` state and their awarded berth returns to the `AVAILABLE` pool. Once no `WON` entries remain, the maintenance sweep closes the round from `DRAWN` to `CLOSED`.

### 3.7. Pump-Out Compliance and Suspension

Vessels with holding tanks must be pumped out on a regular cadence. A pump-out event is logged against a vessel by supplying the `pumpout_date`; the acting role is stamped into the record's `recorded_by_role`, and the record itself is immutable. Logging updates the vessel's `last_pumpout_date` to the most recent pump-out and recomputes its `pumpout_status`. Pump-out records for a vessel can be listed in creation order.

Compliance is measured in whole days against the marina's `pumpout_interval_days`. A vessel becomes non-compliant precisely when the number of days since its reference pump-out date is strictly greater than that interval; at or below the interval it is compliant. When the maintenance sweep finds an `ACTIVE` permit whose vessel has a holding tank and whose days since last pump-out have crossed strictly beyond the interval, it moves the permit from `ACTIVE` to `SUSPENDED`. A suspended permit keeps its berth `OCCUPIED` and still counts toward occupancy. When a later pump-out is logged that restores compliance — after which the days since last pump-out are at or below the interval — the vessel's `pumpout_status` returns to `COMPLIANT` and the permit moves from `SUSPENDED` back to `ACTIVE`.

### 3.8. Derelict-Vessel Enforcement

A harbormaster files a derelict report against a vessel by supplying the `vessel_id` and a free-text `reason`; the report opens in `OPEN` status. Serving notice advances the report from `OPEN` to `NOTICE_SERVED`: the `notice_served_date` is stamped to the current clock, an estimated cost is computed into `estimated_cost_cents`, and a `DERELICT` invoice for that estimate is issued `UNPAID` to the vessel's owner with its identifier recorded in the report's `invoice_id`. The estimate at notice is a flat notice fee of 15,000 cents, with no tow or storage charges.

A served report is closed with a `disposition`. Closing as `RESOLVED` — the owner having cured the problem — advances the report from `NOTICE_SERVED` to the terminal `RESOLVED` state, stamps its `closed_date`, and changes nothing about the vessel or any permit; the `DERELICT` invoice remains payable. Closing as `IMPOUNDED` advances the report to the terminal `IMPOUNDED` state, stamps `closed_date`, and computes the actual cost into `actual_cost_cents`: the actual cost is the 15,000-cent notice fee plus a 40,000-cent tow fee plus a per-day storage charge of 3,000 cents for each storage day, where storage days is the number of whole days between `notice_served_date` and `closed_date`, taken as zero if that difference would be negative, rounded up to a whole day. The `DERELICT` invoice's `amount_due_cents` is raised from the estimate to this actual cost. An impound then sets off a cascade: the vessel's `registration_status` becomes `REVOKED`; because of that, any `ACTIVE` or `SUSPENDED` permit on the vessel is revoked with its refund computed; that permit's berth moves from `OCCUPIED` to `AVAILABLE` with occupancy recomputed; and the freed berth in turn triggers waitlist promotion, which may offer the berth to the next ranked `WAITLISTED` permit. Derelict reports can be listed and filtered by `vessel_id` and `status`.

### 3.9. Launch-Ramp Passes and the Maintenance Sweep

Boaters who only need to launch from the public ramp buy a launch-ramp pass rather than a berth. A ramp pass is created with the `boater_id`, the `vessel_id`, a `pass_type` of `DAY` or `SEASONAL`, and an inclusive validity window given by `valid_from_date` and `valid_to_date`; a `valid_to_date` earlier than `valid_from_date` is rejected with `ERR_INVALID_DATE_RANGE`. The vessel must be `REGISTERED` or the purchase is rejected with `ERR_VESSEL_REGISTRATION_EXPIRED`. The pass copies the boater's residency into `fee_basis` and computes `fee_cents` from the pass type and residency: a seasonal pass costs 8,000 cents for a resident and 20,000 cents for a non-resident, while a day pass costs 1,000 cents for a resident and 3,000 cents for a non-resident. A `RAMP_PASS` invoice is issued `UNPAID` and its identifier stored in the pass's `invoice_id`; the pass begins `ACTIVE`. A boater may not hold two overlapping seasonal ramp passes: for the same boater, two seasonal passes whose closed `valid_from_date`-through-`valid_to_date` intervals overlap — with mere adjacency counting as an overlap — are rejected with `ERR_RAMP_PASS_OVERLAP` (HTTP 409). A pass moves to `EXPIRED` when the clock passes its `valid_to_date`, or a harbormaster may revoke it to `REVOKED`, in which case a still-`UNPAID` `RAMP_PASS` invoice is voided. Ramp passes can be listed and filtered by `boater_id`, `vessel_id`, and `status`.

The maintenance sweep is an operations capability that a harbormaster runs to reconcile the whole marina against the current logical clock in one pass. It expires `ACTIVE` or `SUSPENDED` permits whose season has ended (releasing their berths and running waitlist promotion), declines `OFFERED` permits whose `offer_expires_at` has passed (releasing their berths and running waitlist promotion), suspends `ACTIVE` permits whose vessel pump-out has gone overdue, forfeits `WON` lottery entries whose `claim_deadline` has passed (returning their awarded berths to the pool), expires `ACTIVE` ramp passes past their `valid_to_date`, and closes `DRAWN` lottery rounds once no `WON` entries remain. The sweep itself does not advance the clock; operators move the clock separately and then run the sweep to realize the consequences.

## 4. Endpoint Definitions

Operations that create a new stand-alone resource return `201 Created`; operations that modify or act upon an existing resource, including state transitions and reads, return `200 OK`. Request and response payloads are not repeated here — the fields, side effects, and preconditions for each operation are described in the workflow narratives of §3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/marina/marinas` | Create a marina (config, season window, liveaboard cap) | Harbormaster |
| GET | `/marina/marinas/{marina_id}` | Get a marina with computed occupancy counters | Harbormaster, FinanceClerk, Boater |
| POST | `/marina/marinas/{marina_id}/run-maintenance` | Run the ops sweep at the current logical clock | Harbormaster |
| POST | `/marina/berths` | Create a berth in a marina | Harbormaster |
| GET | `/marina/berths/{berth_id}` | Get a berth | Harbormaster, FinanceClerk, Boater |
| GET | `/marina/berths` | List/filter berths | Harbormaster, FinanceClerk, Boater |
| POST | `/marina/boaters` | Register a boater account | Harbormaster |
| GET | `/marina/boaters/{boater_id}` | Get a boater | Harbormaster, FinanceClerk, Boater |
| POST | `/marina/vessels` | Register a vessel to a boater | Harbormaster, Boater |
| GET | `/marina/vessels/{vessel_id}` | Get a vessel with computed status | Harbormaster, FinanceClerk, Boater |
| GET | `/marina/vessels` | List/filter vessels | Harbormaster, FinanceClerk, Boater |
| POST | `/marina/vessels/{id}/pump-out-records` | Log a pump-out event for a vessel | Harbormaster, Boater |
| GET | `/marina/vessels/{id}/pump-out-records` | List a vessel's pump-out records | Harbormaster, FinanceClerk, Boater |
| POST | `/marina/permits` | Apply for a seasonal permit (immediate offer or waitlist) | Harbormaster, Boater |
| GET | `/marina/permits/{permit_id}` | Get a permit | Harbormaster, FinanceClerk, Boater |
| GET | `/marina/permits` | List/filter permits | Harbormaster, FinanceClerk, Boater |
| POST | `/marina/permits/{permit_id}/cancel` | Withdraw a waitlisted permit or decline an offered one | Harbormaster, Boater |
| POST | `/marina/permits/{permit_id}/revoke` | Revoke an active/suspended permit | Harbormaster |
| POST | `/marina/permits/{permit_id}/transfer` | Transfer an active permit to another boater | Harbormaster |
| POST | `/marina/permits/{permit_id}/reassign-berth` | Reassign an active permit to a different berth (OCC-guarded) | Harbormaster |
| POST | `/marina/lottery-rounds` | Open a seasonal lottery round | Harbormaster |
| GET | `/marina/lottery-rounds/{round_id}` | Get a lottery round | Harbormaster, FinanceClerk, Boater |
| GET | `/marina/lottery-rounds` | List/filter lottery rounds | Harbormaster, FinanceClerk, Boater |
| POST | `/marina/lottery-rounds/{round_id}/draw` | Draw winners deterministically | Harbormaster |
| POST | `/marina/lottery-entries` | Enter a boater and vessel into an open round | Harbormaster, Boater |
| GET | `/marina/lottery-entries/{entry_id}` | Get a lottery entry | Harbormaster, FinanceClerk, Boater |
| GET | `/marina/lottery-entries` | List/filter lottery entries | Harbormaster, FinanceClerk, Boater |
| POST | `/marina/lottery-entries/{entry_id}/claim` | Claim a won entry (creates offered permit and invoice) | Harbormaster, Boater |
| POST | `/marina/derelict-reports` | File a derelict-vessel report | Harbormaster |
| GET | `/marina/derelict-reports/{report_id}` | Get a derelict report | Harbormaster, FinanceClerk, Boater |
| GET | `/marina/derelict-reports` | List/filter derelict reports | Harbormaster, FinanceClerk, Boater |
| POST | `/marina/derelict-reports/{report_id}/serve-notice` | Serve derelict notice and issue the estimate invoice | Harbormaster |
| POST | `/marina/derelict-reports/{report_id}/close` | Close a served report as resolved or impounded | Harbormaster |
| POST | `/marina/ramp-passes` | Buy a launch-ramp pass | Harbormaster, Boater |
| GET | `/marina/ramp-passes/{pass_id}` | Get a ramp pass | Harbormaster, FinanceClerk, Boater |
| GET | `/marina/ramp-passes` | List/filter ramp passes | Harbormaster, FinanceClerk, Boater |
| POST | `/marina/ramp-passes/{pass_id}/revoke` | Revoke a ramp pass | Harbormaster |
| GET | `/marina/invoices/{invoice_id}` | Get an invoice | Harbormaster, FinanceClerk, Boater |
| GET | `/marina/invoices` | List/filter invoices | Harbormaster, FinanceClerk, Boater |
| POST | `/marina/invoices/{invoice_id}/pay` | Pay an invoice in full (a permit invoice activates the permit) | Harbormaster, FinanceClerk, Boater |
| POST | `/marina/invoices/{invoice_id}/waive` | Waive an unpaid invoice | FinanceClerk |
| POST | `/_clock/set_current_utc` | Set the logical clock | Harbormaster |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_UNAUTHORIZED` | 403 Forbidden |
| `ERR_NOT_RESOURCE_OWNER` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_VALIDATION` | 400 Bad Request |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_VESSEL_REGISTRATION_EXPIRED` | 422 Unprocessable Entity |
| `ERR_BERTH_TYPE_MISMATCH` | 422 Unprocessable Entity |
| `ERR_BERTH_SEASON_CONFLICT` | 409 Conflict |
| `ERR_RAMP_PASS_OVERLAP` | 409 Conflict |
| `ERR_VESSEL_TOO_LONG` | 422 Unprocessable Entity |
| `ERR_LIVEABOARD_LIMIT_REACHED` | 422 Unprocessable Entity |
| `ERR_PAYMENT_AMOUNT_MISMATCH` | 422 Unprocessable Entity |
| `ERR_INVOICE_NOT_PAYABLE` | 409 Conflict |
| `ERR_ROUND_NOT_CLOSED_FOR_DRAW` | 409 Conflict |
| `ERR_ROUND_ALREADY_DRAWN` | 409 Conflict |
| `ERR_ENTRY_WINDOW_CLOSED` | 409 Conflict |
| `ERR_CLAIM_DEADLINE_PASSED` | 409 Conflict |
| `ERR_ENTRY_NOT_WON` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_BERTH_NOT_AVAILABLE` | 409 Conflict |
| `ERR_LIVEABOARD_CAP_NEGATIVE` | 400 Bad Request |
| `ERR_INVALID_DATE_RANGE` | 400 Bad Request |
| `ERR_DUPLICATE_LOTTERY_ENTRY` | 409 Conflict |
| `ERR_TRANSFER_TARGET_INVALID` | 422 Unprocessable Entity |
| `ERR_PERMIT_NOT_ACTIVE` | 409 Conflict |
| `ERR_PAGINATION_INVALID` | 400 Bad Request |
