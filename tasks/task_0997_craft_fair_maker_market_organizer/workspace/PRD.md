# Craft Fair Maker Market API — Product Requirements Document

## 1. Introduction

Anyone who has organized a craft fair or maker market knows the operational tangle: a booth map drawn and redrawn as vendors cancel, a jurying spreadsheet where nobody remembers which scores came in, a cashbox reconciliation at midnight after the last booth fee refund, and a weather radar that can undo a week of planning in an hour. This product replaces that tangle with a single API that runs the entire lifecycle of a maker market — from the first floor-plan sketch, through vendor applications and jury review, booth assignment and payment, load-in logistics, gate and ticket operations on the day of the fair, and finally the financial settlement that pays each maker their due.

The system is built around one governing idea: the event itself has a posture, and that posture decides which operations are legal at any moment. Around that spine sit deliberately strict money rules — booth fees and commissions are computed in integer cents under two pinned rounding orders, so that a quoted fee and a charged fee can be audited against each other to the cent — and a segregation-of-duties model in which the people who jury applications, the people who coordinate the event, and the people who approve payouts are never allowed to be the same hands. This document specifies those rules completely: the global contracts every endpoint obeys, the business workflows that drive each state machine, the endpoint inventory, and the error catalogue.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

Every request to the API must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. The system recognizes exactly six roles, spelled precisely as follows: `EventCoordinator`, `Vendor`, `Juror`, `Treasurer`, `GateAgent`, and `PlatformAdmin`. A request missing either header, or carrying a malformed one, is rejected with `ERR_MISSING_AUTH`. A request whose role is not authorized for the attempted operation is rejected with `ERR_FORBIDDEN`.

The meaning of `X-User-ID` depends on the role. When `X-User-Role` is `Vendor`, `X-User-ID` is the `id` of the acting VendorProfile; ownership checks on any resource that references a VendorProfile — an application, an assignment, a settlement, a ledger entry — compare the resource's `vendor_profile_id` to `X-User-ID`. When `X-User-Role` is `EventCoordinator`, `Juror`, `Treasurer`, `GateAgent`, or `PlatformAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it — for example, as `juror_user_id` on a JuryScore or as `approved_by_user_id` on a Settlement — but it does not compare it to any entity's `id` for ownership. Note, however, that the segregation-of-duties rules in §2.9 do compare these opaque identifiers for exclusion: certain actors are forbidden from coinciding, and the recorded identifiers are how the system proves they did not.

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

Endpoints that return lists of resources accept two query parameters. The `limit` parameter sets the maximum number of items returned; when omitted it defaults to 10, and it is bounded below by 1 and above by 100. The `offset` parameter sets how many items to skip and defaults to 0. Unless otherwise specified, every list endpoint returns resources sorted by creation timestamp in ascending order.

List responses carry four pagination fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Event Posture: the Master Gate

Every MakerEvent carries a derived `posture` field whose value is one of `PLANNING`, `APPLICATION_OPEN`, `JURY_REVIEW`, `SCHEDULING`, `LIVE`, `WEATHER_HOLD`, `SETTLEMENT`, `CLOSED`, or `CANCELLED`. The posture is not set directly by clients; it advances through the lifecycle transitions described in §3. The normal progression runs `PLANNING` → `APPLICATION_OPEN` → `JURY_REVIEW` → `SCHEDULING` → `LIVE` → `SETTLEMENT` → `CLOSED`, with `WEATHER_HOLD` branching out of `LIVE` and back, and `CANCELLED` reachable as a terminal outcome from `PLANNING`, `APPLICATION_OPEN`, `JURY_REVIEW`, `SCHEDULING`, or `WEATHER_HOLD`.

The posture is a hard gate on every write that targets a child of the event — applications, scores, assignments, slots, tickets, ledger entries, settlements. When the current posture does not permit the requested child write, the request is rejected with `ERR_POSTURE_FORBIDS`. Independently, when an action endpoint is invoked while its target entity is not in a state from which the requested transition exists, the request is rejected with `ERR_INVALID_STATE`. These two gates sit below authentication and existence checks in the evaluation order: a missing or malformed header surfaces as `ERR_MISSING_AUTH` before anything else, an unauthorized role as `ERR_FORBIDDEN` next, a nonexistent path resource as `ERR_NOT_FOUND` after that, and only then do the posture gate and the per-entity state gate apply, in that order.

### 2.5. The Logical Clock

The system never consults the wall clock. All temporal judgments — application windows, payment deadlines, gate redemption, slot overlap — read a server-side logical clock. At startup, before any client intervention, the logical clock reads exactly `2026-05-01T00:00:00Z`.

A `PlatformAdmin`-only test-driving capability (mounted at `/_clock/set_current_utc`) advances the logical clock to a supplied `to_iso8601` instant and answers with the resulting `now_iso8601`. Advancing the clock is not inert: it triggers the sweep that forfeits any booth assignment whose payment deadline has passed, and it triggers the automatic close of the application window when the clock reaches the window's end.

### 2.6. Common Resource Properties

All primary resources — MakerEvent, BoothZone, Booth, VendorProfile, VendorApplication, BoothAssignment, BoothFeeCharge, LoadInSlot, Ticket, and Settlement — carry a standard set of system-managed fields:

- **`id`** (string): a unique, server-minted identifier formatted as a UUID, with no type prefix.
- **`created_at`** (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was first created.
- **`updated_at`** (string): an ISO 8601 UTC timestamp refreshed on every modification of the resource.
- **`version`** (integer): a system-managed integer that increments with every mutation of the resource; it is the anchor for optimistic concurrency control.

Three resources are deliberately thinner. JuryScore, Attendance, and SalesLedgerEntry are append-only records: they carry `id` and `created_at` only, and both `updated_at` and `version` are absent from them.

Whenever any rule in this document says a resource is mutated — a state change, a cascade, a counter increment — the mutation refreshes that resource's `updated_at` and increments its `version`, for every resource that carries those fields.

### 2.7. Money, Cents, and the Two Rounding Orders

All monetary values in the system are integer cents: zero decimal places, with the round-half-up method used wherever a fractional cent must be resolved. Field values that fail type, enumeration, or range validation — a jury criterion outside its zero-to-ten span, a commission percentage outside zero to twenty-five — are rejected with `ERR_INVALID_INPUT`.

Two rounding orders are pinned deliberately, and they are not interchangeable. The **provisional** booth fee rounds each component to integer cents first and then sums the components; its `rounding_trace` audit string records `per_line_then_sum`. The **final** booth fee sums the exact, unrounded components and rounds once at the end; its `rounding_trace` records `sum_then_round`. The same duality exists on commissions: the quoted commission accumulates rounded per-row amounts in chronological order, while the final commission is computed on the aggregate in a single pass. Because the two orders can diverge by a cent or more on the same inputs, every BoothFeeCharge and every Settlement figure carries an unambiguous statement of which order produced it.

### 2.8. Optimistic Concurrency Control

Two writes in the system carry a mandatory optimistic-concurrency field, and only these two.

Deciding an application (the write that can grant a booth) requires the request to carry `expected_event_version`, holding the MakerEvent `version` the coordinator last observed. If the event's current `version` no longer matches — because the event has been mutated since the coordinator read it — the decision is rejected with `ERR_STALE_VERSION` (HTTP 412), and the coordinator must re-read the event and its booth pool before retrying. Approving a settlement requires the request to carry `expected_settlement_version`, holding the Settlement `version` the treasurer last observed; a mismatch with the settlement's current `version` is likewise rejected with `ERR_STALE_VERSION` (HTTP 412), forcing the treasurer to re-read the figures before blessing them. No endpoint other than these two accepts a version field.

### 2.9. Segregation of Duties

The jury, the coordination desk, and the treasury are kept apart by construction. A juror scoring an application must not be the vendor who filed it, and must not be the coordinator who created the event; the submitted `juror_user_id` is checked against both, and a collision is rejected with `ERR_SOD_VIOLATION`. Symmetrically, the treasurer who approves a settlement — whose identity is recorded as the settlement's `approved_by_user_id` — must not be the coordinator who created the MakerEvent; an approval that fails this check is rejected with `ERR_SOD_VIOLATION`. These two checks guard exactly two writes: the submission of a jury score and the approval of a settlement.

### 2.10. Nested Paths and Hierarchical Consistency

Many resources are addressed through their parents — a booth inside a zone inside an event, a score inside an application inside an event. Nested addresses chain the identifiers `event_id`, `zone_id`, `booth_id`, `vendor_id`, `app_id`, `score_id`, `assignment_id`, `charge_id`, `slot_id`, `ticket_id`, `attendance_id`, `entry_id`, and `settlement_id`, and the server validates them strictly left to right: the first identifier in the path that does not correspond to an existing resource produces an `ERR_NOT_FOUND` rejection, and no identifier further to the right is consulted. A request for a booth under a nonexistent zone therefore fails on the zone before the booth is ever looked up.

Consistency cascades downward as well. When an event is placed on weather hold or cancelled, the system resolves its children — assignments, tickets, settlements, slots — into the terminal states each cascade prescribes, rather than leaving orphaned commitments. Each cascade step is an ordinary mutation of the child it touches: the child's state changes, its `updated_at` refreshes, and its `version` increments.

## 3. Business Logic & Workflows

### 3.1. Standing Up the Fair: the Event, the Booth Map, and the Vendor Registry

An `EventCoordinator` begins by creating the MakerEvent itself, supplying its display `name`, the public `opens_at` and `closes_at` instants, the `venue_capacity` that hard-caps simultaneous on-site attendees, the `application_window_start` and `application_window_end` instants that bound vendor intake, the `jury_quorum` each application must reach before it can be decided, and the two commission percentages — `commission_pct_standard` and the reduced `commission_pct_anchor` granted to anchor booths — each between zero and twenty-five. The event's `weather_flag` may optionally be supplied at creation and defaults to `CLEAR`; its recognized values are `CLEAR`, `ADVISORY`, and `SEVERE`. A new event's `posture` is `PLANNING`.

With the event standing, the coordinator lays out the fairground. Each BoothZone belongs to its event through the system-maintained `maker_event_id` and carries a `label` (such as "North Lawn" or "Pavilion"), a `weather_exposure` of `INDOOR`, `COVERED`, or `OPEN_AIR` — which later determines how deep the weather cascade cuts — a `category` of `CERAMICS`, `TEXTILES`, `JEWELRY`, `WOODWORK`, `FOOD`, or `MIXED`, and a `category_cap`. The cap deserves a precise reading: for any given craft category, the effective ceiling for the whole event is the maximum `category_cap` among the event's zones carrying that category, and it bounds the number of applications that may simultaneously hold `APPROVED` status for that category across the entire event. Within a zone, each Booth is created with a human-readable `code` such as "NL-014", a `tier` of `STANDARD`, `CORNER`, or `ANCHOR`, a `footprint_sqm`, and a base `price_cents`. An `ANCHOR` booth must span at least 20 square meters; creating one smaller is rejected with `ERR_BOOTH_CONSTRAINT_VIOLATION`. A booth's `assigned_application_id` starts empty and is set by the system when an assignment goes active.

Vendors enter the system through a different door: a `PlatformAdmin` registers each VendorProfile with a `display_name`, a `contact_email`, and a two-letter `home_region`. The contact email is unique across all vendors — a duplicate registration is rejected with `ERR_EMAIL_TAKEN` — and a new vendor's `status` is `ACTIVE`. Suspension moves a vendor to `SUSPENDED`, and a suspended vendor is blocked from submitting new applications and from having existing assignments confirmed; either attempt surfaces `ERR_VENDOR_SUSPENDED`.

### 3.2. The Application Window

A vendor's journey into the fair starts with a draft: a `Vendor` creates a VendorApplication against an event by naming the owning `vendor_profile_id`, the `requested_category` (one of the six craft categories), and the `requested_tier`. The application is born in `DRAFT` status, editable and invisible to the jury.

Submitting moves the application from `DRAFT` to `SUBMITTED`, and the gate around that step is fourfold. The event's posture must be `APPLICATION_OPEN`; the logical clock must sit inside the half-open intake window — on or after `application_window_start` and strictly before `application_window_end`, with attempts outside that span rejected as `ERR_APPLICATION_WINDOW_CLOSED`; the vendor's profile must be `ACTIVE`; and the requested category's cap must not already be exhausted by approved applications. The window itself only opens when the coordinator opens applications on an event whose logical clock has reached `application_window_start` and whose `jury_quorum` is at least 2, moving the posture from `PLANNING` to `APPLICATION_OPEN`.

The window closes in one of two ways, with identical effect: the coordinator closes applications by hand, or the logical clock reaches `application_window_end` and the system closes it automatically. Either way the posture advances from `APPLICATION_OPEN` to `JURY_REVIEW`, and the closing sweep resolves every limbo application at once — each application still in `DRAFT` is moved to `WITHDRAWN`, and each application in `SUBMITTED` is moved to `IN_REVIEW`, ready for the jury.

### 3.3. The Jury and the Decision

While the event sits in `JURY_REVIEW`, jurors score the applications before them. A `Juror` submits a scorecard for an application with three criteria — `craftsmanship`, `originality`, and `booth_presentation` — each an integer from 0 to 10, and the card's `total` is their sum, from 0 to 30. The application absorbs each card as it lands: `jury_score_total` accumulates the card totals and `jury_score_count` counts the cards. Each juror may score each application at most once; a second card from the same juror is rejected with `ERR_JURY_DUPLICATE`. The segregation-of-duties rule from §2.9 applies at this moment: the juror must be neither the vendor who filed the application nor the coordinator who created the event, on pain of `ERR_SOD_VIOLATION`.

Decision-making belongs to the `EventCoordinator`, who decides an application by supplying an `outcome` of `APPROVE`, `WAITLIST`, or `REJECT`, together with the OCC token `expected_event_version` described in §2.8. The checks guarding a decision run in a fixed order, so that earlier failures mask later ones: the posture gate first (the event must be in `JURY_REVIEW`, else `ERR_POSTURE_FORBIDS`), then the application's own state (it must be `IN_REVIEW`, else `ERR_INVALID_STATE`), then quorum (`jury_score_count` must reach the event's `jury_quorum`, else `ERR_JURY_QUORUM_NOT_MET`), then the booth constraint for the auto-grant (the granted booth's tier must equal the application's `requested_tier`, else `ERR_BOOTH_CONSTRAINT_VIOLATION`), then the category cap (approving must not push the count of `APPROVED` applications for the `requested_category` above the effective cap for that category, else `ERR_CATEGORY_CAP_EXCEEDED`), then booth occupancy (no other non-terminal assignment on the chosen booth, else `ERR_BOOTH_DOUBLE_BOOKED`), and only last the version check (a stale `expected_event_version` is rejected with `ERR_STALE_VERSION`).

An `APPROVE` outcome does real work. The system grants a booth by selector policy: among booths whose zone category matches the `requested_category`, whose `tier` matches the `requested_tier`, and which are unoccupied, it chooses the lowest-priced; ties break by booth `code` in ascending order, and any remaining tie by the booth's `created_at` in ascending order. Against that booth it creates a BoothAssignment in `PENDING_PAYMENT` status, linked to the application it places through the system-maintained `vendor_application_id`, stamping `assigned_at` with the current logical instant, setting `payment_due_at` exactly 72 hours — three days — after `assigned_at`, and snapshotting the event's current `version` into the assignment's `expected_event_version`. In the same breath it mints the provisional booth fee: a BoothFeeCharge whose `charge_kind` is `PROVISIONAL`, whose `computed_at` records the minting instant, and whose `amount_cents` follows the per-line rounding order. The quote takes the booth's base `price_cents`, applies a tier multiplier of 1.00 for `STANDARD`, 1.25 for `CORNER`, or 1.60 for `ANCHOR`, and applies a category uplift of ten percent for `FOOD` zones, five percent for `MIXED` zones, and no uplift otherwise — a booth's zone lineage is readable through its system-maintained `booth_zone_id`; the tier component — base multiplied by the tier multiplier — is rounded half-up to integer cents, the uplift component — base multiplied by the uplift percentage — is likewise rounded half-up to integer cents, and the provisional amount is the sum of those two rounded components, with `rounding_trace` recording `per_line_then_sum`. Amounts are signed: positive is a charge, negative a refund.

A `WAITLIST` outcome moves the application to `WAITLISTED` — its `waitlist_rank` remaining unset until scheduling begins, since `waitlist_rank` is null unless the application is `WAITLISTED` and the ranking has been materialized — and a `REJECT` outcome moves it to `REJECTED`; neither mints an assignment. Every decision, whatever its outcome, mutates the event itself: the MakerEvent's `version` advances by one and its `updated_at` refreshes. This is precisely why the OCC token matters — a decision taken against a version the coordinator has not observed is refused, never silently applied.

### 3.4. Scheduling, the Waitlist, and Revocation

When the jurying is done, the coordinator begins scheduling, moving the posture from `JURY_REVIEW` to `SCHEDULING`. Two preconditions guard the move. First, no application may remain unresolved — every application must sit in `APPROVED`, `WAITLISTED`, `REJECTED`, or `WITHDRAWN`, and if any application is still in `SUBMITTED` or `IN_REVIEW` the move is rejected with `ERR_UNRESOLVED_APPLICATIONS`. Second, every `APPROVED` application must have met quorum, with a `jury_score_count` of at least `jury_quorum`.

Entering scheduling materializes the waitlist. Independently within each `requested_category`, the system sorts that category's `WAITLISTED` applications by `jury_score_total` from highest to lowest, breaks ties by the application's `created_at` from earliest to latest, and breaks any remaining tie by `vendor_profile_id` in ascending lexicographic order — a last-resort determinism device, never a business signal. The sorted applications receive `waitlist_rank` values 1 through N in that order, and rank 1 is the head of the line for its category.

Promotion from the waitlist is a system act, not a client call. Whenever a BoothAssignment forfeits or a category-cap slot frees up, the promotion scan runs against the affected category and tier: the applicant at the head of the waitlist — the lowest `waitlist_rank` for its `requested_category` — is promoted from `WAITLISTED` to `APPROVED` when the category cap has spare capacity and a booth matching its requested category and tier is unoccupied. Promotion carries exactly the same side effects as an approval at decision time: a `PENDING_PAYMENT` assignment is created and a `PROVISIONAL` fee charge is minted by the per-line quote.

Two exits from `APPROVED` deserve equal attention. A vendor may withdraw an application at any time while it is in `DRAFT`, `SUBMITTED`, `IN_REVIEW`, `WAITLISTED`, or `APPROVED`, moving it to `WITHDRAWN`; withdrawing an `APPROVED` application forfeits its booth assignment — the assignment moves to `FORFEITED` and a refund is minted per policy — and the freed category-cap slot is recomputed from the live counts rather than stored. A coordinator may instead revoke an approved application while the event is in `JURY_REVIEW` or `SCHEDULING`, moving it from `APPROVED` to `CANCELLED`; revocation forfeits the existing assignment, mints a `REFUND` charge, and triggers the waitlist promotion scan.

### 3.5. Paying for the Booth and Planning the Load

An assignment in `PENDING_PAYMENT` becomes real when the vendor pays. Payment moves the assignment from `PENDING_PAYMENT` to `ACTIVE` and is guarded, in order, by the posture gate — the event must be in `SCHEDULING`, `LIVE`, or `WEATHER_HOLD` — by the payment window (the logical clock must be on or before `payment_due_at`; a later attempt is rejected with `ERR_PAYMENT_WINDOW_EXPIRED`), and by a fresh occupancy check on the booth (another assignment in `PENDING_PAYMENT` or `ACTIVE` on the same booth rejects the payment with `ERR_BOOTH_DOUBLE_BOOKED`). Payment mints the final booth fee: a `FINAL` BoothFeeCharge computed by the sum-then-round order — the exact total of base times the tier multiplier plus base times the category uplift, rounded half-up to integer cents in a single rounding — with `rounding_trace` recording `sum_then_round`. On tie-sensitive base prices the final charge can differ from the provisional quote by a cent either way; the `PROVISIONAL` row is never altered and remains for audit. With payment complete, the booth's `assigned_application_id` is set to the application's `id`.

Once the assignment is `ACTIVE`, the vendor confirms the application, moving it from `APPROVED` to `CONFIRMED`; confirmation requires the assignment to be `ACTIVE` and the event to be in `SCHEDULING`, `LIVE`, or `WEATHER_HOLD`.

Assignments also unwind, in three distinct ways that must not be conflated. Forfeiture — available to the vendor or the coordinator, and also fired automatically by the system when the logical clock passes `payment_due_at` — moves an assignment from `PENDING_PAYMENT` or `ACTIVE` to `FORFEITED`. A forfeited assignment mints a `REFUND` charge returning whatever was paid (zero when nothing was), clears the booth's `assigned_application_id`, cancels any Settlement tied to the assignment, and runs the waitlist promotion scan. Release is the gentler coordinator-only instrument: while the event is in `SCHEDULING`, releasing moves a `PENDING_PAYMENT` assignment to `RELEASED` with no refund owed — nothing was ever paid — clearing the booth and running the promotion scan. The booth-occupancy invariant underpins all of this: at most one assignment in `PENDING_PAYMENT` or `ACTIVE` may exist per booth at any moment — a boolean occupancy rule, deliberately distinct from the time-interval rule for load slots below.

Load logistics run on bays. A vendor or the coordinator reserves a LoadInSlot by naming the `booth_assignment_id` it serves, a `kind` of `LOAD_IN` or `LOAD_OUT`, the `starts_at` and `ends_at` instants, and a `bay` of `NORTH` or `SOUTH`. Slots are half-open intervals — a slot occupies the span from `starts_at` inclusive to `ends_at` exclusive — and two slots conflict only when they share both bay and kind and their spans genuinely intersect: a new slot conflicts with an existing one when it starts before the existing slot ends and the existing slot starts before the new one ends. Equivalently, there is no conflict when the new slot ends at or before the existing slot's start, or starts at or after the existing slot's end — back-to-back reservations on the same bay are explicitly permitted. A conflicting reservation is rejected with `ERR_SLOT_OVERLAP`.

### 3.6. Tickets, the Gate, and the Weather

Tickets go on sale through the coordinator or a `PlatformAdmin`, each recording a `purchaser_email` — deliberately not unique — a `kind` of `GA`, `EARLY_BIRD`, or `VIP`, and a `price_cents` face value. A new ticket's `state` is `ISSUED` and its `redeemed_at` is null. `VIP` tickets include early entry and, crucially for the gate, count double against the venue's occupancy projection.

None of it matters until the fair goes live. The coordinator moves the event from `SCHEDULING` to `LIVE` only when at least one BoothAssignment stands in `ACTIVE` and every assignment still in `PENDING_PAYMENT` has a `payment_due_at` later than the current logical instant; going live makes tickets redeemable at the gate.

Redemption is the `GateAgent`'s province and is checked synchronously. Redeeming a ticket moves it from `ISSUED` to `REDEEMED`, stamps `redeemed_at`, and appends an Attendance row carrying the `ticket_id`, an `entered_at` equal to the current logical instant, and a null `exited_at` while the guest remains on site. Three conditions reject a redemption with `ERR_TICKET_NOT_REDEEMABLE`: the ticket is not in `ISSUED`, the `weather_flag` is `SEVERE`, or the posture is anything but `LIVE`. Capacity is the fourth gate, with its own error: effective occupancy counts every Attendance row of the event whose `exited_at` is still null, then adds one more for each such row whose ticket is a `VIP`; admission is granted only while that effective occupancy is strictly below `venue_capacity`. The last successful scan is therefore the one taken while effective occupancy equals `venue_capacity` minus one; any attempt at equality or beyond is rejected with `ERR_VENUE_AT_CAPACITY`. When a guest leaves, the gate records an exit scan that sets the Attendance row's `exited_at` to the current instant, and the event's attendance listing supports an `on_site` filter for the rows still open.

Refunds follow the ticket's state. An `ISSUED` ticket may be refunded — moving it to `REFUNDED` — whenever the event's posture is one of `PLANNING`, `APPLICATION_OPEN`, `JURY_REVIEW`, `SCHEDULING`, or `WEATHER_HOLD`, or whenever the supplied `reason` is `EVENT_CANCELLED`, regardless of posture. A `REDEEMED` ticket may be refunded only when its Attendance row shows a non-null `exited_at` and the `reason` is `EVENT_CANCELLED`. Every other combination of state and reason is rejected with `ERR_TICKET_NOT_REFUNDABLE`.

Weather is the live event's wildcard. The coordinator sets the event's `weather_flag`, and setting it to `SEVERE` while the event is `LIVE` slams the event into `WEATHER_HOLD` with a four-part cascade: ticket redemption is suspended; every BoothAssignment in an `OPEN_AIR` zone whose status is `ACTIVE` is moved to `FORFEITED`; each forfeited assignment releases its booth, clearing `assigned_application_id`; and each forfeiture mints a `REFUND` BoothFeeCharge per the weather refund policy. The state machine defines automatic posture changes only for these two flag values — `SEVERE` into the hold, and `CLEAR` back out of it: while in `WEATHER_HOLD`, setting the flag to `CLEAR` returns the event to `LIVE` provided the logical clock is still before `closes_at`. `ADVISORY` is a recognized intermediate flag value for record-keeping.

Cancellation has two distinct shapes, and the difference matters. Cancelling from `WEATHER_HOLD` moves the event to `CANCELLED` and resolves everything outstanding: every ticket in `ISSUED` or `REDEEMED` is refunded at full face value to `REFUNDED`; every assignment in `PENDING_PAYMENT` or `ACTIVE` becomes `FORFEITED`; every settlement in `PENDING` or `COMPUTED` becomes `CANCELLED`; and every LoadInSlot is deleted outright. Cancelling earlier — from `PLANNING`, `APPLICATION_OPEN`, `JURY_REVIEW`, or `SCHEDULING` — takes the pre-live shape instead: all tickets are voided to `VOIDED` rather than refunded, every application in a non-terminal state is moved to `WITHDRAWN`, and all booth assignments are `RELEASED`. From any other posture the cancel action is not a valid transition and is rejected with `ERR_INVALID_STATE`.

### 3.7. Sales, Settlement, and Closing the Books

During the fair, each vendor posts their own takings: a SalesLedgerEntry names the `booth_assignment_id` making the sale and a signed `gross_cents` — positive for a sale, negative for a refund, in which case the entry's `reversal_of_entry_id` points at the entry it compensates and marks the row as a compensation row. The server stamps `recorded_at` at posting. These rows are the raw material of settlement, and like jury scores and attendance they are append-only: no `updated_at`, no `version`.

The settlement phase begins when the coordinator ends the event. Ending requires the logical clock to have reached `closes_at`, and it requires every guest to have left — any Attendance row with a null `exited_at` rejects the move with `ERR_UNRESOLVED_ATTENDANCE`. Ending moves the posture from `LIVE` to `SETTLEMENT` and, in the same act, synthesizes one Settlement in `PENDING` status for every BoothAssignment still `ACTIVE`. The provisional fee rows of those assignments are frozen at this moment, each to be paired with its final recomputation when its settlement is computed.

Computation belongs to the `Treasurer` and runs only while the event is in `SETTLEMENT` posture; it accepts a settlement in `PENDING` or `DISPUTED` and refuses any other state with `ERR_SETTLEMENT_NOT_COMPUTABLE`. The evaluation order is pinned, because the steps lean on each other. First, `gross_sales_cents`: the assignment's ledger rows are walked in chronological order — by `recorded_at` ascending, ties broken by `created_at` ascending — and each row's signed `gross_cents` accumulates, compensation rows subtracting as their negative amounts land; the accumulated gross is then floored at zero, since excess refunds are tracked separately rather than driving the gross negative. Second, `commission_cents`, by the quoted (per-row) variant: the rows are walked in the same chronological order while a running cumulative gross is maintained; the applicable percentage for every row is `commission_pct_anchor` when the booth's tier is `ANCHOR` and `commission_pct_standard` otherwise; the first 100,000 cents of cumulative gross — one thousand dollars — are charged at that base percentage, and anything above the threshold is charged at two percentage points more. A single row that straddles the threshold is split: the portion bringing the cumulative total up to 100,000 cents is rounded half-up at the base percentage, and the remainder is rounded half-up at the bumped percentage; every row's commission is rounded half-up to integer cents as it is processed, and a cumulative gross of exactly 100,000 cents is charged entirely at the base percentage. Compensation rows subtract commission against the tier they originally hit. Third, the outstanding booth fee is taken as the final booth fee minus what has already been paid, never below zero. Finally, `net_payout_cents` is the gross minus the commission minus the outstanding booth fee. Reordering these steps is not a stylistic choice — any other order can produce different cents where the threshold straddle or the rounding-order gap bites.

A vendor who disagrees with a computed settlement — verified by ownership, the caller's `X-User-ID` matching the VendorProfile `id` behind the underlying application — may dispute it, optionally with a `reason`, moving it from `COMPUTED` to `DISPUTED`. Dispute is not a dead end: the treasurer recomputes, moving the settlement back to `COMPUTED`, and the `DISPUTED` → `COMPUTED` loop may cycle indefinitely until the parties converge.

Approval is the treasury's solemn step, and it is guarded in a fixed order. The settlement must be in `COMPUTED`, else `ERR_SETTLEMENT_NOT_APPROVABLE`. The segregation-of-duties rule then applies: the approver's `X-User-ID` — recorded on the settlement as `approved_by_user_id` — must differ from the identifier of the coordinator who created the event, else `ERR_SOD_VIOLATION`. Finally the OCC rule from §2.8 applies: the request must carry `expected_settlement_version` matching the settlement's current `version`, else `ERR_STALE_VERSION` with HTTP 412 — a treasurer who has not re-read the figures since they last changed may not bless them. A successful approval moves the settlement to `APPROVED` and, as with any mutation, increments its `version` and refreshes `updated_at`.

Payment closes the loop. Marking a settlement paid requires it to be `APPROVED`, else `ERR_SETTLEMENT_NOT_PAYABLE`, and moves it to `PAID`. At that moment the commission is re-quoted by the final (aggregate) variant and persisted as the audit figure: the assignment's whole ledger is netted into a single gross total with compensations included; if that total exceeds 100,000 cents, the commission is the base percentage on the first 100,000 cents rounded half-up, plus the bumped percentage — base plus two percentage points — on the remainder, rounded half-up; otherwise it is the base percentage on the whole total, rounded half-up once. A settlement in `PENDING` or `COMPUTED` may instead be cancelled by the treasurer, moving it to `CANCELLED`, and the system cascades of §3.6 can land it there as well.

The fair itself closes when the books are clean: the coordinator may move the event from `SETTLEMENT` to `CLOSED` only when no settlement remains in `PENDING`, `COMPUTED`, or `DISPUTED` — every settlement must be `APPROVED` or `PAID` — and any straggler rejects the close with `ERR_UNRESOLVED_SETTLEMENTS`. `CLOSED` and `CANCELLED` are the event's two terminal postures, and with `PAID` and `CANCELLED` the terminal states of every settlement beneath it, the season is done.

## 4. Endpoint Definitions

Throughout the API, operations that create a new resource — an event, a zone, a booth, a vendor profile, an application, a jury score, a load slot, a ticket, a sales ledger entry — return `201 Created`. Operations that modify an existing resource or drive a state transition, as well as all reads, return `200 OK`. The table below is a navigational summary only; the request and response content of each operation is specified by the workflows in §3 and the contracts in §2.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the logical clock | PlatformAdmin |
| POST | `/maker-events` | Create a MakerEvent | EventCoordinator |
| GET | `/maker-events` | List MakerEvents | EventCoordinator, Treasurer, Vendor, Juror, GateAgent, PlatformAdmin |
| GET | `/maker-events/{event_id}` | Read one MakerEvent | EventCoordinator, Treasurer, Vendor, Juror, GateAgent, PlatformAdmin |
| POST | `/maker-events/{event_id}/open-applications` | Open the application window | EventCoordinator |
| POST | `/maker-events/{event_id}/close-applications` | Close the application window | EventCoordinator |
| POST | `/maker-events/{event_id}/begin-scheduling` | Move from jury review to scheduling | EventCoordinator |
| POST | `/maker-events/{event_id}/go-live` | Open the gates | EventCoordinator |
| POST | `/maker-events/{event_id}/end-event` | End the event and synthesize settlements | EventCoordinator |
| POST | `/maker-events/{event_id}/close-event` | Close the event after settlement | EventCoordinator |
| POST | `/maker-events/{event_id}/cancel` | Cancel the event with cascade | EventCoordinator |
| POST | `/maker-events/{event_id}/weather` | Set the weather flag; SEVERE triggers the hold cascade | EventCoordinator |
| POST | `/maker-events/{event_id}/booth-zones` | Create a BoothZone | EventCoordinator |
| GET | `/maker-events/{event_id}/booth-zones` | List BoothZones for an event | EventCoordinator, Treasurer, Vendor, Juror, GateAgent, PlatformAdmin |
| GET | `/booth-zones/{zone_id}` | Read a single BoothZone | EventCoordinator, Treasurer, Vendor, Juror, GateAgent, PlatformAdmin |
| GET | `/booth-zones` | Filtered list of BoothZones by event | EventCoordinator, Treasurer, Vendor, Juror, GateAgent, PlatformAdmin |
| POST | `/maker-events/{event_id}/booth-zones/{zone_id}/booths` | Create a Booth in a zone | EventCoordinator |
| GET | `/maker-events/{event_id}/booth-zones/{zone_id}/booths` | List Booths in a zone (filterable by `tier`, `occupied`) | EventCoordinator, Treasurer, Vendor, Juror, GateAgent, PlatformAdmin |
| GET | `/booths/{booth_id}` | Read a single Booth | EventCoordinator, Treasurer, Vendor, Juror, GateAgent, PlatformAdmin |
| GET | `/booths` | Filtered list of Booths by zone or assigned application | EventCoordinator, Treasurer, Vendor, Juror, GateAgent, PlatformAdmin |
| POST | `/vendor-profiles` | Register a VendorProfile | PlatformAdmin |
| GET | `/vendor-profiles/{vendor_id}` | Read a VendorProfile | EventCoordinator, Treasurer, Vendor, PlatformAdmin |
| POST | `/vendor-profiles/{vendor_id}/suspend` | Suspend a vendor | PlatformAdmin |
| GET | `/vendor-profiles/{vendor_id}/applications` | List applications filed by this vendor | EventCoordinator, Treasurer, Vendor, PlatformAdmin |
| POST | `/maker-events/{event_id}/applications` | Create a draft VendorApplication | Vendor |
| GET | `/maker-events/{event_id}/applications` | List applications for an event | EventCoordinator, Treasurer, Juror, Vendor, PlatformAdmin |
| GET | `/maker-events/{event_id}/applications/{app_id}` | Read one application | EventCoordinator, Treasurer, Juror, Vendor, PlatformAdmin |
| GET | `/applications/{app_id}` | Canonical single application read | EventCoordinator, Treasurer, Juror, Vendor, PlatformAdmin |
| GET | `/applications` | Filtered list of applications | EventCoordinator, Treasurer, Juror, Vendor, PlatformAdmin |
| POST | `/maker-events/{event_id}/applications/{app_id}/submit` | Submit a draft application | Vendor |
| POST | `/maker-events/{event_id}/applications/{app_id}/withdraw` | Withdraw a non-terminal application | Vendor |
| POST | `/maker-events/{event_id}/applications/{app_id}/decide` | Decide an application; auto-grants a booth on approval (OCC on the event) | EventCoordinator |
| POST | `/maker-events/{event_id}/applications/{app_id}/revoke` | Revoke an approved application | EventCoordinator |
| POST | `/maker-events/{event_id}/applications/{app_id}/jury-scores` | Submit a jury score; one per juror per application | Juror |
| GET | `/maker-events/{event_id}/applications/{app_id}/jury-scores` | List jury scores for an application | EventCoordinator, Juror, Treasurer, PlatformAdmin |
| GET | `/jury-scores` | Filtered list of jury scores | EventCoordinator, Juror, Treasurer, PlatformAdmin |
| GET | `/jury-scores/{score_id}` | Read a single jury score | EventCoordinator, Juror, Treasurer, PlatformAdmin |
| GET | `/maker-events/{event_id}/assignments` | List BoothAssignments for an event | EventCoordinator, Treasurer, Vendor, PlatformAdmin |
| GET | `/maker-events/{event_id}/assignments/{assignment_id}` | Read one BoothAssignment | EventCoordinator, Treasurer, Vendor, PlatformAdmin |
| GET | `/booth-assignments/{assignment_id}` | Canonical single assignment read | EventCoordinator, Treasurer, Vendor, PlatformAdmin |
| GET | `/booth-assignments` | Filtered list of assignments by booth or application | EventCoordinator, Treasurer, Vendor, PlatformAdmin |
| POST | `/maker-events/{event_id}/assignments/{assignment_id}/pay` | Pay for an assignment; mints the final fee charge | Vendor |
| POST | `/maker-events/{event_id}/assignments/{assignment_id}/forfeit` | Forfeit an assignment; mints a refund and runs the waitlist scan | Vendor, EventCoordinator |
| POST | `/maker-events/{event_id}/assignments/{assignment_id}/release` | Release an unpaid assignment (no refund) | EventCoordinator |
| POST | `/maker-events/{event_id}/assignments/{assignment_id}/confirm` | Confirm the application behind an active assignment | Vendor |
| GET | `/maker-events/{event_id}/assignments/{assignment_id}/charges` | List fee charges for an assignment | EventCoordinator, Treasurer, Vendor, PlatformAdmin |
| GET | `/booth-fee-charges` | Filtered list of fee charges by assignment | EventCoordinator, Treasurer, Vendor, PlatformAdmin |
| GET | `/booth-fee-charges/{charge_id}` | Read a single fee charge | EventCoordinator, Treasurer, Vendor, PlatformAdmin |
| POST | `/maker-events/{event_id}/load-in-slots` | Reserve a load-in or load-out slot on a bay | Vendor, EventCoordinator |
| GET | `/maker-events/{event_id}/load-in-slots` | List load slots for an event | EventCoordinator, Vendor, PlatformAdmin |
| GET | `/load-in-slots/{slot_id}` | Read a single load slot | EventCoordinator, Vendor, PlatformAdmin |
| GET | `/load-in-slots` | Filtered list of load slots | EventCoordinator, Vendor, PlatformAdmin |
| POST | `/maker-events/{event_id}/tickets` | Sell a ticket | EventCoordinator, PlatformAdmin |
| GET | `/maker-events/{event_id}/tickets` | List tickets for an event | EventCoordinator, Treasurer, GateAgent, PlatformAdmin |
| GET | `/maker-events/{event_id}/tickets/{ticket_id}` | Read a ticket | EventCoordinator, Treasurer, GateAgent, PlatformAdmin |
| GET | `/tickets/{ticket_id}` | Canonical single ticket read | EventCoordinator, Treasurer, GateAgent, PlatformAdmin |
| GET | `/tickets` | Filtered list of tickets by event | EventCoordinator, Treasurer, GateAgent, PlatformAdmin |
| POST | `/maker-events/{event_id}/tickets/{ticket_id}/redeem` | Redeem a ticket at the gate | GateAgent |
| POST | `/maker-events/{event_id}/tickets/{ticket_id}/refund` | Refund a ticket with constraints | EventCoordinator |
| GET | `/maker-events/{event_id}/attendance` | List attendance rows for an event | EventCoordinator, Treasurer, GateAgent, PlatformAdmin |
| GET | `/attendance/{attendance_id}` | Read a single attendance row | EventCoordinator, Treasurer, GateAgent, PlatformAdmin |
| GET | `/attendance` | Filtered list of attendance rows | EventCoordinator, Treasurer, GateAgent, PlatformAdmin |
| POST | `/maker-events/{event_id}/attendance/{attendance_id}/exit` | Record an exit scan | GateAgent |
| POST | `/maker-events/{event_id}/sales-ledger` | Post a sale or a compensating refund | Vendor |
| GET | `/maker-events/{event_id}/sales-ledger` | List sales ledger entries for an event | EventCoordinator, Treasurer, Vendor, PlatformAdmin |
| GET | `/sales-ledger-entries/{entry_id}` | Read a single ledger entry | EventCoordinator, Treasurer, Vendor, PlatformAdmin |
| GET | `/sales-ledger-entries` | Filtered list of ledger entries | EventCoordinator, Treasurer, Vendor, PlatformAdmin |
| GET | `/maker-events/{event_id}/settlements` | List settlements for an event | EventCoordinator, Treasurer, Vendor, PlatformAdmin |
| GET | `/maker-events/{event_id}/settlements/{settlement_id}` | Read one settlement | EventCoordinator, Treasurer, Vendor, PlatformAdmin |
| GET | `/settlements/{settlement_id}` | Canonical single settlement read | EventCoordinator, Treasurer, Vendor, PlatformAdmin |
| GET | `/settlements` | Filtered list of settlements by assignment | EventCoordinator, Treasurer, Vendor, PlatformAdmin |
| POST | `/maker-events/{event_id}/settlements/{settlement_id}/compute` | Compute or recompute a settlement | Treasurer |
| POST | `/maker-events/{event_id}/settlements/{settlement_id}/approve` | Approve a computed settlement (SoD and OCC) | Treasurer |
| POST | `/maker-events/{event_id}/settlements/{settlement_id}/dispute` | Dispute a computed settlement | Vendor |
| POST | `/maker-events/{event_id}/settlements/{settlement_id}/mark-paid` | Mark an approved settlement paid; locks the final commission | Treasurer |
| POST | `/maker-events/{event_id}/settlements/{settlement_id}/cancel` | Cancel a pending or computed settlement | Treasurer |

## 5. Error Code Catalogue

The catalogue below enumerates every machine-readable error the API can return. The conditions under which each error fires are specified in the narratives of §2 and §3, not here.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_AUTH` | 400 Bad Request |
| `ERR_FORBIDDEN` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_POSTURE_FORBIDS` | 409 Conflict |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_SOD_VIOLATION` | 403 Forbidden |
| `ERR_JURY_QUORUM_NOT_MET` | 409 Conflict |
| `ERR_JURY_DUPLICATE` | 409 Conflict |
| `ERR_CATEGORY_CAP_EXCEEDED` | 409 Conflict |
| `ERR_APPLICATION_WINDOW_CLOSED` | 409 Conflict |
| `ERR_BOOTH_CONSTRAINT_VIOLATION` | 422 Unprocessable Entity |
| `ERR_BOOTH_DOUBLE_BOOKED` | 409 Conflict |
| `ERR_SLOT_OVERLAP` | 409 Conflict |
| `ERR_PAYMENT_WINDOW_EXPIRED` | 409 Conflict |
| `ERR_VENUE_AT_CAPACITY` | 409 Conflict |
| `ERR_TICKET_NOT_REDEEMABLE` | 409 Conflict |
| `ERR_TICKET_NOT_REFUNDABLE` | 409 Conflict |
| `ERR_SETTLEMENT_NOT_COMPUTABLE` | 409 Conflict |
| `ERR_SETTLEMENT_NOT_APPROVABLE` | 409 Conflict |
| `ERR_SETTLEMENT_NOT_PAYABLE` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_VENDOR_SUSPENDED` | 409 Conflict |
| `ERR_EMAIL_TAKEN` | 409 Conflict |
| `ERR_UNRESOLVED_APPLICATIONS` | 409 Conflict |
| `ERR_UNRESOLVED_SETTLEMENTS` | 409 Conflict |
| `ERR_UNRESOLVED_ATTENDANCE` | 409 Conflict |
| `ERR_INVALID_INPUT` | 400 Bad Request |
