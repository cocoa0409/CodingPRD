# Master-Planned Community Developer Operations API — Product Requirements Document

## 1. Introduction

Developing a master-planned community is a decade-long exercise in keeping promises. The developer sells homebuilders on a takedown schedule for platted lots, sells residents on amenities that must exist before their neighbors do, funds roads and utilities through a reimbursement district that must be accounted to the cent, and — by statute — must progressively surrender control of the community association to the homeowners as closings accumulate. Each of these obligations interacts with the others: a single lot closing can escalate a builder's tranche, breach an amenity delivery trigger, cancel a poolside event, nudge the community across a governance threshold, and convert a board seat from declarant-appointed to owner-elected, all in one transaction.

This document specifies the Master-Planned Community Developer Operations API, the system of record for that entire operating surface. It covers phase rollout and amenity delivery commitments, builder lot purchase agreements and their takedown tranches, escrow and closing cascades, association budgets and annual assessment setting under a statutory cap, infrastructure reimbursement district accounting with certified interest, architectural design review and covenant enforcement, lifestyle programming and the sales center, resident records and statutory notices, and the board election mechanics that carry the community from declarant control to recorded turnover. All operations run against a server-owned logical clock so that statutory deadlines, lead-time windows, and scheduled sweeps are deterministic and testable. The API is mounted under `/mpc`, with a platform-level clock control endpoint mounted separately.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming the operational capacity in which they act. The system recognizes nine roles, spelled exactly as follows: `DeclarantExecutive`, `DeclarantController`, `BuilderRep`, `AssociationDirector`, `OwnerDirector`, `DesignReviewer`, `LifestyleCoordinator`, `HomeownerResident`, and `PlatformAdmin`. A request whose `X-User-Role` is missing or does not name one of these roles, or whose `X-User-ID` is missing, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401); the platform clock endpoint is authenticated under the same rule. A request whose named role is not in the target endpoint's authorized role list is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403).

The meaning of `X-User-ID` depends on the role. When `X-User-Role` is `BuilderRep`, `X-User-ID` is the `id` of the acting `Builder`; ownership checks on any resource that references a `Builder` compare the resource's foreign-key field (for example, an agreement's `builder_id`) to `X-User-ID`. When `X-User-Role` is `HomeownerResident`, `X-User-ID` is the `id` of the acting `Resident`, and ownership checks likewise compare resident foreign keys (for example, an RSVP's `resident_id`) to `X-User-ID`. When `X-User-Role` is `OwnerDirector`, `X-User-ID` is also the `id` of a `Resident` — specifically one who holds a `FILLED` `OWNER_ELECTED` board seat. When `X-User-Role` is `DeclarantExecutive`, `DeclarantController`, `AssociationDirector`, `DesignReviewer`, `LifestyleCoordinator`, or `PlatformAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it (for example, as `adopted_by_user_id` on an `AssociationBudget`, as `fined_by_user_id` on a `DesignViolation`, or as `requested_by_user_id` on a `ReimbursementPayment`) but does not compare it to any entity's `id`. The same `ERR_FORBIDDEN_ROLE` rejection fires when an entity-backed actor operates on another principal's resource — for instance, a `BuilderRep` curing a tranche that belongs to a different builder's agreement.

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
- The `api_request_timestamp` is a server-generated ISO 8601 UTC timestamp with three fractional digits. Every timestamp the server emits is rendered in this same form — ISO 8601 UTC with exactly three fractional digits and a trailing `Z` — including resource `created_at` and `updated_at` (§2.4), the domain timestamp fields of §3, and the clock endpoint's `current_utc`.
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

List endpoints are paginated through two query parameters. The `limit` parameter sets the maximum number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter sets the number of items skipped and defaults to 0.

Unless a collection's own specification says otherwise, every list endpoint returns resources sorted by `created_at` in ascending order. (The board-seat collection is the documented exception: it is ordered by `seat_no` ascending.)

Paginated list responses carry the fields `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the response envelope.

### 2.4. Common Resource Properties

Every resource in this API — communities, phases, amenities, builders, agreements, tranches, lots, closings, budgets, line items, assessment rates, districts, advances, levies, payments, design applications, violations, events, RSVPs, appointments, residents, notices, and board seats — carries a standard set of system-managed fields:

- **`id` (string):** a server-minted UUID, with no type prefix.
- **`created_at` (string):** an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created.
- **`updated_at` (string):** an ISO 8601 UTC timestamp refreshed on any mutation of the resource.
- **`version` (integer):** a system-managed integer that increments with every modification to the resource.

Both `created_at` and `updated_at` are stamped from the logical clock (§2.5), never from wall-clock time — a resource created before any clock-setting call carries `created_at` `2026-05-01T00:00:00.000Z`.

Beyond these four, nearly every resource also carries a domain-specific `status` field whose enumerated values and transition rules are given with its lifecycle in §3. System-driven mutations count. When a cascade described in §3 changes a resource — for example, executing an agreement, commencing, terminating, or amending it increments the `LotPurchaseAgreement` `version`; proposing, adopting, ratifying, rejecting, revising, or superseding a budget increments the `AssociationBudget` `version` — that resource's `updated_at` refreshes and its `version` advances even though the client never addressed it directly.

### 2.5. The Logical Clock and the Clock Sweep

The server keeps a single logical clock that governs every timestamped rule in this document. Before any clock-setting call, the clock reads exactly `2026-05-01T00:00:00Z`; it never falls back to wall-clock time. A `PlatformAdmin` advances it through the clock endpoint with a `to_iso8601` instant; the response reports the resulting `current_utc` and a `transitions_applied` count.

Setting the clock runs a sweep that applies every scheduled transition whose moment has arrived: tranches whose due date is within thirty days open (`SCHEDULED` → `OPEN`), tranches past due with an unmet count are marked `MISSED` (demoting their builder to `PROBATION`), scheduled notices are sent (`SCHEDULED` → `SENT`), events whose end has passed complete (`SCHEDULED` → `COMPLETED`), armed assessment rates become `EFFECTIVE` at fiscal-year start, approved design applications past their construction-start window lapse to `EXPIRED`, called elections past their deadline lapse to `LAPSED`, and amenities whose statutory outside date has passed without opening become `DELINQUENT`. Business narratives in §3 refer to "the logical clock" or "the sweep" wherever these automatic transitions matter.

### 2.6. Money, Percentages, and Rounding

All monetary amounts are integers denominated in cents — prices, penalties, fines, budgets, levies, advances, and payments alike. Wherever a monetary calculation produces a fraction, the result is rounded half-up to a whole cent. Rounding is applied at exactly the points the calculation narratives in §3 specify: the escalated base price of a lot is rounded half-up to whole cents once, before the lot premium is added; an annual assessment per unit is rounded half-up to whole cents first, and only then are quarterly installments derived from that rounded annual amount — never by rounding per-quarter figures directly from the assessment gap.

Percentages (the closed-unit percentage, assessment increase percentages) are rounded half-up to two decimal places, and threshold comparisons against them use the rounded value with an inclusive boundary: a value of exactly the threshold qualifies. District interest is computed per advance and rounded half-up to whole cents per advance before summing, for both the simple-interest provisional figure and the daily-compound certified figure.

### 2.7. Governance Posture: the Transition-Stage Ratchet

Each community carries a computed governance posture, `transition_stage`, derived from the ratio of closed homes to the total planned build-out. The `closed_unit_pct` is the community's `closed_unit_count` divided by its `total_planned_units`, multiplied by 100, rounded half-up to two decimal places. The stage mapping, evaluated on the rounded percentage with inclusive thresholds, is: at least 25.00 percent → `OWNER_REPRESENTATION`; at least 50.00 percent → `PARITY`; at least 75.00 percent → `OWNER_MAJORITY`; otherwise `DECLARANT_CONTROL`. Reaching 100.00 percent does not itself complete turnover — the stage remains `OWNER_MAJORITY` until statutory turnover is recorded, at which point it becomes `TURNOVER_COMPLETE`.

The stage is a ratchet: it advances when a closing crosses a threshold and it never regresses, including when a closing is rescinded and the closed-unit percentage falls. Governance powers key off this stage throughout §3 — budget adoption paths, assessment cap override ratification, the declarant subsidy election, and the end of declarant authority are all expressed in terms of it.

### 2.8. Versioned Amendments and Optimistic Concurrency Control

Two write operations are create-with-supersede amendments and are guarded by optimistic concurrency control. Creating a superseding takedown amendment against a lot purchase agreement (`POST /mpc/agreements/{aid}/amendments`) requires the request to carry `expected_agreement_version`, the client must supply its last-observed `version` of that agreement, and if the value does not match the agreement's current `version` the request is rejected with `ERR_STALE_VERSION` (HTTP 412). Creating a successor draft budget that supersedes an adopted budget (`POST /mpc/budgets/{bid}/amendments`) likewise requires `expected_budget_version` matching the budget's current `version`, with the same `ERR_STALE_VERSION` (HTTP 412) rejection on mismatch. The version field on these two endpoints is non-optional. Endpoints not listed here do not take a version field at all; no other operation performs an OCC check.

### 2.9. Validation Order and Error Precedence

Every request is validated against a fixed ladder, and a failure at an earlier rung masks every later rung. The order is:

1. **Authentication** — the headers of §2.1; failures surface as `ERR_UNAUTHENTICATED`.
2. **Authorization** — the role named by `X-User-Role` must appear in the endpoint's authorized list; otherwise `ERR_FORBIDDEN_ROLE`.
3. **Existence** — path identifiers are validated left-to-right, then every foreign-key identifier in the request body (`community_id`, `phase_id`, `builder_id`, `agreement_id`, `lot_id`, `budget_id`, `district_id`, `event_id`, `resident_id`, `owner_resident_id`, `holder_resident_id`, `trigger_phase_id`, `charged_budget_id`, `assessment_rate_id`, applicant and respondent identifiers); each missing resource yields its own `ERR_*_NOT_FOUND` (HTTP 404).
4. **Request shape** — required fields present, primitive types correct, enum members valid, no undeclared fields, scalar constraints honored; otherwise `ERR_VALIDATION` (HTTP 400).
5. **State** — the target must be in a valid from-state for the requested transition (`ERR_INVALID_STATE`, HTTP 409), plus the domain state gates of §3 such as `ERR_COMMUNITY_NOT_ACTIVE`, `ERR_PHASE_NOT_OPEN_FOR_SALES`, `ERR_AGREEMENT_NOT_ACTIVE`, `ERR_LOT_NOT_OFFERED`, `ERR_LOT_NOT_UNDER_CONTRACT`, `ERR_BUILDER_NOT_IN_GOOD_STANDING`, `ERR_OUTSTANDING_COMPLIANCE_DEFAULTS`, `ERR_CLOSEOUT_BLOCKED`, `ERR_CLOSINGS_PENDING`, `ERR_BUDGET_EMPTY`, `ERR_BUDGET_NOT_ADOPTED`, `ERR_NOTICE_NOT_SENT`, `ERR_TRANCHE_NOT_CURABLE`, `ERR_CURE_WINDOW_OPEN`, `ERR_SEAT_NOT_VACANT`, `ERR_REVIEW_ROUNDS_EXHAUSTED`, `ERR_DECLARANT_AUTHORITY_ENDED`, `ERR_SUBSIDY_NOT_AVAILABLE`, `ERR_NO_PRIOR_RATE`, `ERR_TRANSITION_THRESHOLD_NOT_MET`, and `ERR_TURNOVER_SEATS_NOT_FILLED`.
6. **Concurrency** — the OCC check of §2.8, surfacing as `ERR_STALE_VERSION`.
7. **Business safety** — the amenity-posture guard on event scheduling, `ERR_AMENITY_NOT_OPEN`.
8. **Temporal windows** — lead times, statutory windows, and future-dating rules: `ERR_EVENT_LEAD_TIME`, `ERR_NOTICE_LEAD_TIME`, `ERR_RESCISSION_WINDOW_EXPIRED`, `ERR_APPEAL_WINDOW_EXPIRED`, `ERR_SEND_AT_IN_PAST` (HTTP 422).
9. **Uniqueness, overlap, sequence, and segregation** — `ERR_PHASE_SEQUENCE_BLOCKED`, `ERR_DUPLICATE_FISCAL_YEAR`, `ERR_DUPLICATE_ASSESSMENT_YEAR`, `ERR_DUPLICATE_DISTRICT`, `ERR_DUPLICATE_TRANCHE_NO`, `ERR_VENUE_OVERLAP`, `ERR_TOUR_CAPACITY_REACHED` (all HTTP 409), and the segregation-of-duties conflicts `ERR_REVIEWER_CONFLICT`, `ERR_ADOPTER_CANNOT_RATIFY`, `ERR_HEARING_OFFICER_CONFLICT` (HTTP 403), together with the election thresholds `ERR_QUORUM_NOT_MET` and `ERR_ELECTION_MAJORITY_NOT_REACHED` (HTTP 409). Duplicate `parcel_number` or resident `email` within a community surfaces as `ERR_VALIDATION`.
10. **Cross-entity referential consistency** — `ERR_LOT_PHASE_MISMATCH`, `ERR_APPLICANT_IDENTITY_INVALID`, `ERR_RESPONDENT_IDENTITY_INVALID`, `ERR_FISCAL_YEAR_MISMATCH`, `ERR_RESIDENT_COMMUNITY_MISMATCH`, `ERR_TRANCHE_COVERAGE_MISMATCH`, `ERR_HOLDER_NOT_ELIGIBLE` (HTTP 422).
11. **Fiscal guards, evaluated last** — `ERR_INSUFFICIENT_DISTRICT_FUNDS`, `ERR_PAYMENT_EXCEEDS_OBLIGATION`, `ERR_EVENT_BUDGET_EXCEEDED`, `ERR_PENALTY_AMOUNT_MISMATCH` (HTTP 402), and `ERR_ASSESSMENT_CAP_EXCEEDED` (HTTP 422).

### 2.10. Resource Lookup and Reference Validation

When a request path contains multiple resource identifiers, the server validates them sequentially from left to right and rejects with the 404 error corresponding to the first identifier that does not resolve; later identifiers are not examined. Foreign keys supplied in request bodies are validated after the path resolves, in the same existence rung of the ladder. Each resource type has its own not-found error — `ERR_COMMUNITY_NOT_FOUND`, `ERR_PHASE_NOT_FOUND`, `ERR_AMENITY_NOT_FOUND`, `ERR_BUILDER_NOT_FOUND`, `ERR_AGREEMENT_NOT_FOUND`, `ERR_TRANCHE_NOT_FOUND`, `ERR_LOT_NOT_FOUND`, `ERR_CLOSING_NOT_FOUND`, `ERR_BUDGET_NOT_FOUND`, `ERR_LINE_ITEM_NOT_FOUND`, `ERR_RATE_NOT_FOUND`, `ERR_DISTRICT_NOT_FOUND`, `ERR_ADVANCE_NOT_FOUND`, `ERR_LEVY_NOT_FOUND`, `ERR_PAYMENT_NOT_FOUND`, `ERR_APPLICATION_NOT_FOUND`, `ERR_VIOLATION_NOT_FOUND`, `ERR_EVENT_NOT_FOUND`, `ERR_RSVP_NOT_FOUND`, `ERR_APPOINTMENT_NOT_FOUND`, `ERR_RESIDENT_NOT_FOUND`, `ERR_NOTICE_NOT_FOUND`, `ERR_BOARD_SEAT_NOT_FOUND` — so a caller can always tell which reference failed.

The resource graph itself is flat: every collection is a peer under `/mpc`, and parent-child relationships are expressed through foreign keys in request bodies and through filtered list queries rather than through nested URLs. For example, lots of a phase are retrieved by filtering the lots collection by `phase_id`, tranches of an agreement by filtering the tranches collection by `agreement_id`, and the notices superseding a given notice by filtering the notices collection by `supersedes_notice_id`.

## 3. Business Logic & Workflows

### 3.1. Founding a Community and Seating the Declarant Board

A `DeclarantExecutive` founds a community by supplying its `community_name` and the `total_planned_units` — the total residential units planned at full build-out, which must be at least 1 and which becomes the fixed divisor for both the closed-unit percentage and the per-unit assessment math. A new community begins in `PLANNING` status with `closed_unit_count` zero and `transition_stage` `DECLARANT_CONTROL`.

Activation moves the community from `PLANNING` to `ACTIVE`. The activation payload carries `declarant_director_names`, which must contain exactly five entries — one per board seat — or the request fails with `ERR_VALIDATION`. On activation the system creates five `BoardSeat` rows numbered `seat_no` 1 through 5, each `DECLARANT_APPOINTED` and `FILLED`, with `holder_name` taken from the supplied names. The community remains in `DECLARANT_CONTROL` at this point; activation seats the declarant board but does not itself advance the governance posture.

A read-only governance dashboard is available for each community, exposing `closed_unit_count`, `closed_unit_pct`, `transition_stage`, and the counts `owner_elected_seats_filled` and `owner_elected_seats_vacant` for the owner-elected delegation.

### 3.2. Phase Rollout and Amenity Delivery Obligations

Build-out proceeds phase by phase. A `DeclarantExecutive` creates a `DevelopmentPhase` with a `phase_name`, a `sequence_no` (at least 1, unique within the community) that fixes its position in the rollout, and a `planned_lot_count` of at least 1; the phase starts `PLANNED` with `closed_lot_count` zero. Opening sales moves the phase from `PLANNED` to `SALES_OPEN` and is gated twice: the community must be `ACTIVE` (otherwise `ERR_COMMUNITY_NOT_ACTIVE`), and the phase with the immediately preceding `sequence_no` in the same community, when one exists, must already be `DELIVERING` or `CLOSED_OUT` (otherwise `ERR_PHASE_SEQUENCE_BLOCKED`; the same error fires when the `sequence_no` itself is already used in the community). A phase advances from `SALES_OPEN` to `DELIVERING` automatically the moment its first lot closing reaches `CLOSED`.

Closing out a `DELIVERING` phase requires that every lot in the phase be in `CLOSED` or `WITHDRAWN` and that every agreement drawing on the phase be in `COMPLETED`, `DEFAULTED`, or `TERMINATED`; either shortfall is rejected with `ERR_CLOSEOUT_BLOCKED`. A `PLANNED` or `SALES_OPEN` phase may instead be cancelled, but only while no closing in `PENDING` or `CLOSED` references any of its lots (again `ERR_CLOSEOUT_BLOCKED`). Cancellation cascades: the phase's lots in `PLATTED` or `OFFERED` move to `WITHDRAWN`, and its agreements in `DRAFT` or `EXECUTED` move to `TERMINATED` with their tranches in `SCHEDULED` or `OPEN` moving to `CANCELLED`.

Amenities are the public face of the delivery promise. A `DeclarantExecutive` commits an `Amenity` with an `amenity_type` of `CLUBHOUSE`, `POOL`, `PARK`, `TRAIL_NETWORK`, `FITNESS_CENTER`, or `EVENT_LAWN`; a statutory outside date `hard_deadline_date`; and a `budgeted_cost_cents` of zero or more. Delivery may also be keyed to sell-through: `trigger_phase_id` and `trigger_unit_count` form a nullable pair — either both are present or neither is, and when present the amenity must be `OPEN` before the trigger phase's `closed_lot_count` exceeds `trigger_unit_count`. Amenities can be listed by community or filtered by `trigger_phase_id`.

An amenity progresses from `COMMITTED` to `IN_DESIGN` to `UNDER_CONSTRUCTION` to `OPEN` under the `DeclarantExecutive`'s direction, and `OPEN` is terminal. Two independent breach conditions drop a not-yet-open amenity into `DELINQUENT`: the sweep passing its `hard_deadline_date`, or a closing-driven trigger breach — whenever the trigger phase's `closed_lot_count` increments, every amenity keyed to that phase whose status is not already `OPEN` or `DELINQUENT` is checked, and a count strictly greater than `trigger_unit_count` breaches it (the closing that makes the count exactly equal to `trigger_unit_count` is safe). Entering `DELINQUENT` stamps `delinquency_recorded_at` with the logical clock and fires a three-part cascade: every `SCHEDULED` community event whose venue maps to this amenity's type is cancelled, with its RSVPs cancelled in turn (this is reachable precisely because scheduling an event only requires the venue's amenity to be under construction); and a `DRAFT` resident notice of type `AMENITY_DELINQUENCY` is auto-created for the community. A late opening is always permitted — `DELINQUENT` → `OPEN` — but the events cancelled by the delinquency are not restored.

### 3.3. Builder Agreements and the Takedown Schedule

Before a merchant builder can buy lots, a `DeclarantExecutive` credentials it for a community with its `legal_name` and a `credit_tier` of `A`, `B`, or `C`. The builder's `standing` starts at `GOOD_STANDING` with `total_lots_purchased` at zero. Standing is enforced automatically: the moment any tranche of any of the builder's agreements becomes `MISSED`, the builder drops to `PROBATION`; the moment any of its agreements becomes `DEFAULTED`, it drops to `SUSPENDED`. A `DeclarantExecutive` may reinstate a builder to `GOOD_STANDING` only when no tranche of any of its agreements remains `MISSED` or `DEFAULTED` — and, when reinstating from `SUSPENDED`, additionally when no agreement of the builder is `DEFAULTED`; outstanding compliance defaults are rejected with `ERR_OUTSTANDING_COMPLIANCE_DEFAULTS`.

A `DeclarantController` drafts a `LotPurchaseAgreement` naming the `community_id`, the purchasing `builder_id`, and the `phase_id` whose lots the agreement draws from, together with the commercial terms: `base_price_per_lot_cents` (greater than zero), `annual_escalation_pct` (zero or more), `penalty_per_lot_per_day_cents` (zero or more), `earnest_money_cents` (zero or more), and `total_lots_committed` (at least 1). The draft starts in `DRAFT` with `lots_closed_count` and `forfeited_earnest_money_cents` at zero and `execution_date` null. Against a `DRAFT` agreement, the controller adds `TakedownTranche` rows — each with a `tranche_no` unique within the agreement (duplicates are rejected `ERR_DUPLICATE_TRANCHE_NO`), a `due_date`, and a `lot_count_due` of at least 1, representing the lots due by that date for that tranche alone, not cumulatively. Each tranche's `cure_deadline` is computed as its `due_date` plus fourteen days, and its `lots_credited` and `accrued_penalty_cents` start at zero in `SCHEDULED` status.

Execution moves the agreement from `DRAFT` to `EXECUTED` under a `DeclarantExecutive` and enforces four gates: the community must be `ACTIVE` (`ERR_COMMUNITY_NOT_ACTIVE`), the builder must be in `GOOD_STANDING` (`ERR_BUILDER_NOT_IN_GOOD_STANDING`), the phase must be `SALES_OPEN` or `DELIVERING` (`ERR_PHASE_NOT_OPEN_FOR_SALES`), and the tranche schedule must exactly cover the commitment — the sum of `lot_count_due` across the agreement's tranches must equal `total_lots_committed` (`ERR_TRANCHE_COVERAGE_MISMATCH`). Execution stamps `execution_date` from the logical clock and increments the agreement's `version`. A `DeclarantController` then commences the agreement, `EXECUTED` → `ACTIVE`, beginning the takedown obligations.

Tranches live on the clock. The sweep opens a `SCHEDULED` tranche when the logical clock reaches thirty days before its `due_date` (`SCHEDULED` → `OPEN` while the clock is earlier than the due date). An `OPEN` tranche becomes `SATISFIED` automatically when the closing waterfall raises its `lots_credited` to `lot_count_due`. Past the due date with the count still short, the sweep marks it `MISSED`, which demotes the builder from `GOOD_STANDING` to `PROBATION` and starts the penalty meter. The accrued penalty on a `MISSED` tranche is evaluated on read, at cure, and at default certification: the deficit is `lot_count_due` minus `lots_credited`; the days late are the calendar days from `due_date` to the evaluation moment (zero while the tranche is not `MISSED`); the raw penalty is the deficit times the agreement's `penalty_per_lot_per_day_cents` times the days late; and `accrued_penalty_cents` is the lesser of that raw figure and a cap of twenty-five percent of `lot_count_due` times the agreement's `base_price_per_lot_cents`, the cap itself rounded half-up to whole cents.

A `MISSED` tranche has three exits. The builder's own `BuilderRep` may cure it — the acting user's `X-User-ID` must equal the agreement's `builder_id` (`ERR_FORBIDDEN_ROLE` otherwise) — by paying `payment_cents` exactly equal to the current `accrued_penalty_cents` (`ERR_PENALTY_AMOUNT_MISMATCH` on any other amount) while the logical clock is on or before the `cure_deadline`; attempting to cure a tranche that is not `MISSED`, or one whose cure deadline has already passed, is rejected with `ERR_TRANCHE_NOT_CURABLE`. A cured tranche moves to `CURED`. An `AssociationDirector` may waive it, moving it to `WAIVED` with a recorded `waiver_reason` and forgiving the accrued penalty — it is frozen at its current value and no longer owed — but only while the community's `transition_stage` is not `TURNOVER_COMPLETE` (`ERR_DECLARANT_AUTHORITY_ENDED`). Or a `DeclarantExecutive` may certify the default once the cure window has closed — the logical clock must be strictly after the `cure_deadline` (`ERR_CURE_WINDOW_OPEN` while it is still open) — moving the tranche to `DEFAULTED`.

Certifying a default is the heaviest cascade in the system. The tranche's agreement becomes `DEFAULTED`: its `forfeited_earnest_money_cents` is set to the full `earnest_money_cents`, and the builder's standing drops to `SUSPENDED`. That demotion itself cascades — the builder's other agreements in `DRAFT` or `EXECUTED` are `TERMINATED`, and their tranches in `SCHEDULED` or `OPEN` are `CANCELLED`. The same terminal housekeeping applies when a `DeclarantExecutive` terminates an agreement voluntarily: termination is available from `DRAFT`, `EXECUTED`, or `ACTIVE` only while no closing of the agreement is `PENDING` (`ERR_CLOSINGS_PENDING`), and it cancels the agreement's `SCHEDULED` and `OPEN` tranches. On the success path, an `ACTIVE` agreement completes automatically — `ACTIVE` → `COMPLETED` — when its `lots_closed_count` reaches `total_lots_committed` and every tranche sits in `SATISFIED`, `CURED`, or `WAIVED`.

While an agreement is `EXECUTED` or `ACTIVE`, a `DeclarantController` may replace the remaining takedown schedule through the OCC-guarded amendment operation described in §2.8. The request carries `expected_agreement_version` and a `replacement_tranches` schedule; the replacement must re-cover the outstanding obligation, meaning its `lot_count_due` total equals `total_lots_committed` minus `lots_closed_count` (`ERR_TRANCHE_COVERAGE_MISMATCH` otherwise). The amendment atomically cancels the agreement's non-terminal tranches in `SCHEDULED` or `OPEN`, creates the replacements as new `SCHEDULED` tranches, and increments the agreement's `version`.

### 3.4. Lot Conveyance and the Closing Cascade

Lots are platted into phases. A `DeclarantExecutive` plats a `Lot` by naming its `phase_id` and its assessor `parcel_number` — unique within the community, with duplicates rejected as `ERR_VALIDATION` — plus an optional `lot_premium_cents` (zero or more, defaulting to 0) for view, corner, or oversize premiums. The lot's `community_id` is denormalized from the owning phase at creation. A new lot is `PLATTED`; offering it moves it to `OFFERED` and requires the phase to be `SALES_OPEN` or `DELIVERING` (`ERR_PHASE_NOT_OPEN_FOR_SALES`); an `OFFERED` lot may be pulled back to `WITHDRAWN`.

A `DeclarantController` opens escrow by creating a `LotClosing` with an `agreement_id`, a `lot_id`, and an optional `owner_resident_id` naming the end-buying resident (null for builder bulk holds). Creation requires the agreement to be `ACTIVE` (`ERR_AGREEMENT_NOT_ACTIVE`), the lot to be `OFFERED` (`ERR_LOT_NOT_OFFERED`), and the lot to belong to the agreement's phase (`ERR_LOT_PHASE_MISMATCH`); the closing starts `PENDING`, its `community_id` is denormalized from the agreement, and the lot moves automatically from `OFFERED` to `UNDER_CONTRACT`. Cancelling a `PENDING` closing returns the lot to `OFFERED`. Closings can be listed with filters on `agreement_id`, `lot_id`, `owner_resident_id`, `credited_tranche_id`, or `community_id`.

Recording the close — `PENDING` → `CLOSED`, again by a `DeclarantController`, again gated on the agreement being `ACTIVE` and the lot being `UNDER_CONTRACT` (`ERR_LOT_NOT_UNDER_CONTRACT`) — is the system's central transaction, and its effects land in a fixed order. First the price is fixed. `closing_date` is stamped from the logical clock. The escalated base counts the agreement's anniversaries: the number of calendar dates formed by adding whole years to `execution_date` that fall on or before the `closing_date` — a closing exactly on an anniversary counts that anniversary, and before the first anniversary the count is zero. `escalated_base_cents` is the agreement's `base_price_per_lot_cents` compounded by `annual_escalation_pct` percent per elapsed anniversary, rounded half-up to a whole cent. `premium_cents` captures the lot's `lot_premium_cents` at the moment of close, and `price_cents` is the escalated base plus the premium.

Second, the takedown waterfall credits exactly one lot. Eligible tranches are the agreement's tranches in `OPEN` or `MISSED` status with `lots_credited` still below `lot_count_due` — `SCHEDULED` tranches are not eligible, so early closings cannot pre-credit future tranches. The waterfall picks the eligible tranche with the earliest `due_date`, breaking ties by ascending `tranche_no`, increments its `lots_credited` by one, records it as the closing's `credited_tranche_id`, and flips it to `SATISFIED` when the credit completes its count. When no tranche is eligible, the closing is an over-takedown: `credited_tranche_id` is null and `is_surplus` is true. Exactly one lot is credited per closing; there is no spill to a second tranche.

Third, the closing cascade propagates outward. The lot moves to `CLOSED`; if its phase was `SALES_OPEN` it advances to `DELIVERING`, and the phase's `closed_lot_count` increments — that increment itself runs the amenity trigger-breach check of §3.2, which can drop a breached amenity to `DELINQUENT` and set off the event-cancellation and delinquency-notice cascade from there. The agreement's `lots_closed_count` increments, the builder's `total_lots_purchased` increments, and the agreement completion check runs. The community's `closed_unit_count` increments, `closed_unit_pct` is recomputed, and `transition_stage` ratchets up across any crossed thresholds per §2.7 — which converts declarant-appointed board seats to owner-elected vacancies per §3.9. Finally, when `owner_resident_id` is set, that resident becomes an `OWNER` with `owner_since` stamped to the `closing_date`.

A closing can be undone in two ways. Cancellation of a `PENDING` closing simply returns the lot to `OFFERED`. Rescission of a `CLOSED` closing is a `DeclarantExecutive` action available only within thirty days of the `closing_date` — later attempts are rejected `ERR_RESCISSION_WINDOW_EXPIRED` — and it moves the closing to `RESCINDED` and unwinds the close: the credited tranche, when `credited_tranche_id` is set, loses one credit and, if it had been `SATISFIED`, reverts to `OPEN` when the logical clock is still on or before its `due_date` and to `MISSED` when the due date has passed; `closed_unit_count`, `closed_lot_count`, `lots_closed_count`, and `total_lots_purchased` each decrement and `closed_unit_pct` is recomputed; the lot returns to `OFFERED`; and the resident, if any, remains an `OWNER`. Because of the ratchet, `transition_stage` does not regress even though the percentage falls.

### 3.5. Budgets, Assessments, and the Statutory Cap

Association finance follows an annual cycle of proposal, notice, adoption, and assessment. A `DeclarantController` drafts an `AssociationBudget` for a `community_id` and a `fiscal_year` (2020 or later), optionally offsetting the assessment requirement with `non_assessment_income_cents` (zero or more, default 0). Only one budget per community and fiscal year may exist outside `SUPERSEDED` status; a duplicate is rejected `ERR_DUPLICATE_FISCAL_YEAR`. Line items are added while the budget is `DRAFT`: each `BudgetLineItem` names its `budget_id`, a `category` of `LANDSCAPE_MAINTENANCE`, `AMENITY_OPERATIONS`, `UTILITIES`, `MANAGEMENT`, `INSURANCE`, `RESERVE_CONTRIBUTION`, `EVENTS_PROGRAMMING`, or `CONTINGENCY`, an `amount_cents` greater than zero, and an `is_reserve` flag (default false) marking lines that fund the reserve account. The budget's `total_expense_cents` — the sum of all line amounts — and its `reserve_cents` — the sum over reserve lines only — are recomputed as lines are added.

Proposal moves the budget from `DRAFT` to `PROPOSED` and requires at least one line item (`ERR_BUDGET_EMPTY`). Adoption is where governance posture bites, and two statutory notice gates apply first: a resident notice of type `BUDGET_ADOPTION` referencing this budget via `budget_id` must exist in `SENT` status (otherwise `ERR_NOTICE_NOT_SENT`; a superseded notice does not count even if it was sent), and that notice's `sent_at` must be at least fourteen days before the adoption moment (otherwise `ERR_NOTICE_LEAD_TIME`). Then the stage decides the path. Under `DECLARANT_CONTROL` or `OWNER_REPRESENTATION`, an `AssociationDirector` adopts directly to `ADOPTED`. Under `PARITY` or `OWNER_MAJORITY`, the same adopt action lands the budget in `PENDING_RATIFICATION`, and an `OwnerDirector` must ratify it — the ratifier's `X-User-ID` must differ from the recorded `adopted_by_user_id` (`ERR_ADOPTER_CANNOT_RATIFY`), enforcing segregation between the adopter and the ratifier. After turnover, adoption belongs to the owners: at `TURNOVER_COMPLETE` an `OwnerDirector` adopts directly, while an `AssociationDirector` attempting it is rejected `ERR_DECLARANT_AUTHORITY_ENDED`. Every successful adopt records `adopted_by_user_id` from the acting header.

Rejection is available to an `AssociationDirector` from either `PROPOSED` or `PENDING_RATIFICATION`, and a `REJECTED` budget returns to `DRAFT` through the controller's revise action — a full revision loop. Separately, an `ADOPTED` budget can be amended: the OCC-guarded amendment (§2.8, `expected_budget_version` required) atomically marks the current budget `SUPERSEDED`, creates a successor `DRAFT` budget whose `amendment_of_id` points at its predecessor and whose line items are copied over, increments the superseded budget's `version`, and cascades to any assessment rates derived from the superseded budget in `CALCULATED` or `ARMED` status, moving them to `SUPERSEDED`.

From an `ADOPTED` budget, a `DeclarantController` computes the year's `AssessmentRate`. The rate's `fiscal_year` must equal its budget's (`ERR_FISCAL_YEAR_MISMATCH`), the referenced budget must be `ADOPTED` (`ERR_BUDGET_NOT_ADOPTED`), and only one non-`SUPERSEDED` rate may exist per community and fiscal year (`ERR_DUPLICATE_ASSESSMENT_YEAR`). The assessment gap is the budget's `total_expense_cents` — reserve lines included — minus its `non_assessment_income_cents`, and every planned unit is assessable: the divisor is the community's `total_planned_units`, so the declarant effectively carries the share of unsold inventory.

Two variants exist. Under the uniform variant (`subsidy_elected` false, the default), `per_unit_annual_cents` is the gap divided by `total_planned_units`, rounded half-up to a whole cent, and `declarant_subsidy_cents` is 0. Under the declarant-subsidy variant, the election is validated in a fixed order: first, `transition_stage` must be `DECLARANT_CONTROL` (otherwise `ERR_SUBSIDY_NOT_AVAILABLE`), and second, an `EFFECTIVE` rate must exist for the prior fiscal year (otherwise `ERR_NO_PRIOR_RATE`). When both hold, the owner rate freezes at the prior year's per-unit amount, `increase_pct` reports 0.00, and `declarant_subsidy_cents` is the gap minus the frozen per-unit amount multiplied by `total_planned_units`.

Whenever an `EFFECTIVE` rate exists for the prior fiscal year it is linked as `prior_rate_id` and its per-unit amount captured as `prior_per_unit_cents`; `increase_pct` is then the excess of the new `per_unit_annual_cents` over `prior_per_unit_cents`, expressed as a percentage of the prior amount and rounded half-up to two decimals. With no prior rate, `prior_rate_id`, `prior_per_unit_cents`, and `increase_pct` are all null. The quarterly schedule `quarterly_installments_cents` derives strictly from the rounded annual amount: the first three quarters are each the annual amount divided by four, rounded half-up to whole cents, and the fourth quarter is the annual amount minus those three, so the four installments sum exactly to the annual figure.

A computed rate starts `CALCULATED`. Arming it is gated on notice and on the statutory cap. A resident notice of type `ASSESSMENT_CHANGE` referencing the rate via `assessment_rate_id` must exist in `SENT` status (`ERR_NOTICE_NOT_SENT`), and its `sent_at` must be no later than thirty days before midnight UTC on January 1 of the rate's fiscal year (`ERR_NOTICE_LEAD_TIME`). The cap applies only when `increase_pct` is non-null: an increase of 20.00 percent or less passes without ceremony — the boundary is inclusive — while anything above requires `cap_override_approved_by` to be set, and when `transition_stage` is `PARITY` or `OWNER_MAJORITY` it additionally requires `cap_override_ratified_by`; arming without the required override fails with `ERR_ASSESSMENT_CAP_EXCEEDED`. The override is approved through the approve-cap-override action — by an `AssociationDirector` before turnover or an `OwnerDirector` after — which stamps `cap_override_approved_by`, and ratified through the ratify-cap-override action by an `OwnerDirector`, which stamps `cap_override_ratified_by` and must be a different user than the approver. Arming itself belongs to the `DeclarantController` before turnover and to the `OwnerDirector` after; a `DeclarantController` attempting to arm at `TURNOVER_COMPLETE` is rejected `ERR_DECLARANT_AUTHORITY_ENDED`. Once `ARMED`, the sweep flips the rate to `EFFECTIVE` when the logical clock reaches midnight UTC on January 1 of its fiscal year.

### 3.6. The Infrastructure Reimbursement District

Roads, water, and sewer are financed through a reimbursement district. A `DeclarantController` creates at most one `ReimbursementDistrict` per community (`ERR_DUPLICATE_DISTRICT`), naming it (`district_name`, in the MUD/PID/CFD style) and fixing its `interest_rate_annual_pct` (zero or more). The district's balances start at zero: `advance_principal_cents`, `outstanding_principal_cents`, `provisional_interest_cents`, `certified_interest_to_date_cents`, and `available_funds_cents`.

Developer advances are recorded with a `district_id`, an `amount_cents` greater than zero, the `advance_date` from which interest accrues, and an optional `description` of the infrastructure. Each advance immediately raises the district's `advance_principal_cents` and `outstanding_principal_cents` by its amount. An advance's own status is derived, never set: `OUTSTANDING` while nothing has been reimbursed, `PARTIALLY_REIMBURSED` while its `reimbursed_principal_cents` is greater than zero but below its `amount_cents`, and `REIMBURSED` once the two are equal; a rejection unwind that returns `reimbursed_principal_cents` to zero moves it back to `OUTSTANDING`.

Interest is tracked two ways. The provisional figure, recomputed whenever the district is read and before any certification, is simple interest to the logical clock: for each advance, regardless of status, take its `amount_cents` times the annual rate over one hundred times the days outstanding over 365 — days outstanding being the calendar days from `advance_date` to now, or zero when the advance date is today or in the future — rounded half-up to whole cents per advance, then summed into `provisional_interest_cents`. The certified figure, computed only at payment certification, compounds daily per advance to the certification timestamp: each advance accrues its `amount_cents` times the quantity one plus the annual rate over one hundred over 365, raised to the days outstanding, minus one — again rounded half-up to whole cents per advance and summed in first-in-first-out order. For identical data the certified figure is larger than the provisional one.

Funding arrives through annual levies. A `DistrictLevy` is planned with a `district_id`, a `levy_year` unique within the district, and an `amount_cents` greater than zero, starting `PLANNED`; collecting it stamps `collected_at` from the logical clock, moves it to `COLLECTED`, and adds its amount to the district's `available_funds_cents` — the district's spendable balance, defined as collected levies minus the amounts of payments already `PAID`.

Reimbursement claims follow a strict segregation of duties: the `DeclarantController` who requests a payment (recorded as `requested_by_user_id` at creation, starting the payment in `REQUESTED`) is never the one who certifies or rejects it — certification and rejection belong to an `AssociationDirector`. Certification audits the claim. The claimed `amount_cents` may not exceed the district's `outstanding_principal_cents` plus the daily-compound interest accrued across all advances to the certification moment (`ERR_PAYMENT_EXCEEDS_OBLIGATION`). The certified interest, `certified_interest_cents`, is the sum of the daily-compound interest over all advances to that timestamp, and the certified principal, `certified_principal_cents`, is the claim amount minus that interest — a claim too small to cover the interest due would make that figure negative and is likewise rejected `ERR_PAYMENT_EXCEEDS_OBLIGATION`. The waterfall then allocates interest-first globally and principal to advances first-in-first-out, ordered by `advance_date` ascending with ties broken by `created_at` ascending: each advance's `reimbursed_principal_cents` grows until it reaches its `amount_cents` (becoming `REIMBURSED`), and overflow rolls to the next advance. Certification stamps `certified_at`, debits the district's `outstanding_principal_cents` by the certified principal, and credits `certified_interest_to_date_cents` by the certified interest.

Disbursement moves a `CERTIFIED` payment to `PAID` under a `DeclarantController` and requires the district's `available_funds_cents` to cover the payment's `amount_cents` (`ERR_INSUFFICIENT_DISTRICT_FUNDS`); it stamps `paid_at` and draws the funds down. Rejection is available from `REQUESTED` with no unwind, and from `CERTIFIED` with a full compensating unwind: the district's `outstanding_principal_cents` is restored by the certified principal, `certified_interest_to_date_cents` is reduced by the certified interest, and the advance allocations are unwound in reverse first-in-first-out order — the most recent allocations come off first.

### 3.7. Design Review and Covenant Enforcement

During build-out, exterior work is gated through design review. An application is submitted by its own applicant — a `BuilderRep` whose `X-User-ID` equals the `applicant_builder_id`, or a `HomeownerResident` whose `X-User-ID` equals the `applicant_resident_id` (`ERR_FORBIDDEN_ROLE` otherwise) — naming the `community_id`, the `lot_id`, and a `project_type` of `NEW_CONSTRUCTION`, `EXTERIOR_MODIFICATION`, `LANDSCAPE`, or `ADDITION`. Exactly one of the two applicant identifiers must be present (`ERR_APPLICANT_IDENTITY_INVALID`). A new application starts `SUBMITTED` at `submission_round` 1 with `review_fee_cents` 0.

A `DesignReviewer` claims an application by beginning review, which stamps `reviewer_user_id` and moves it to `UNDER_REVIEW`. Two conflict rules protect impartiality: on a first submission the reviewer's `X-User-ID` must not equal the applicant's id, and on a `RESUBMITTED` application it must not equal the `denied_by_user_id` of the latest denial; both surface as `ERR_REVIEWER_CONFLICT`. The same exclusivity binds decisions: approving, approving with conditions, and denying each require the actor to be the recorded `reviewer_user_id` (`ERR_REVIEWER_CONFLICT`). Approval stamps `construction_start_by` at the logical clock plus 180 days; conditional approval records `conditions_text` and leaves the application `CONDITIONALLY_APPROVED` until the reviewer verifies the conditions, at which point it becomes `APPROVED` and `construction_start_by` is set the same way. Denial records a `denial_reason` and stamps `denied_by_user_id`; a denial landing at the third round leaves the application `DENIED` with no further resubmission path — the review loop is exhausted in practice.

An applicant may resubmit a `DENIED` application while `submission_round` is below three rounds (`ERR_REVIEW_ROUNDS_EXHAUSTED` beyond that), provided the acting user matches the applicant — the `BuilderRep`'s id matching `applicant_builder_id` or the `HomeownerResident`'s id matching `applicant_resident_id` (`ERR_FORBIDDEN_ROLE`). Resubmission increments `submission_round` and assesses the round fee: `review_fee_cents` becomes 25000 cents entering round 2 and 75000 cents entering round 3. Withdrawal is available to the applicant from `SUBMITTED` or `DENIED` under the same identity match. An `APPROVED` application is protected from expiry once the applicant records the start of construction; otherwise, when the logical clock passes `construction_start_by` with no construction start recorded, the sweep lapses it to `EXPIRED`.

Covenant enforcement runs on a parallel track. A `DesignReviewer` or `AssociationDirector` reports a `DesignViolation` with a `community_id`, a `lot_id`, a `violation_type` of `UNAPPROVED_MODIFICATION`, `NONCONFORMING_MATERIALS`, `SETBACK`, or `LANDSCAPE_DEADLINE`, and exactly one respondent — `respondent_resident_id` or `respondent_builder_id` (`ERR_RESPONDENT_IDENTITY_INVALID`). A report starts `REPORTED`; sending notice moves it to `NOTICE_SENT` and sets the `cure_deadline` fourteen days out. The violation's `days_late` measures the calendar days from `cure_deadline` to the earliest of the cure timestamp, the fine timestamp, and the current clock — zero while the deadline has not passed.

Recording a cure stamps `cured_at`, freezes `days_late`, and moves the violation to `CURED`; curing on or before the deadline keeps `fine_cents` at 0. Escalation past the deadline (`ERR_CURE_WINDOW_OPEN` while the cure window is still open) moves the violation to `ESCALATED`, after which an `AssociationDirector` schedules a hearing — `hearing_date` must be strictly after the logical clock (`ERR_SEND_AT_IN_PAST`) — moving it to `HEARING_SCHEDULED`. Levying the fine moves it to `FINED`, stamps `fined_by_user_id`, freezes `days_late`, and computes `fine_cents` on a tiered schedule at the levy timestamp: the first thirty days late accrue 5000 cents per day, days thirty-one through sixty accrue 10000 cents per day, and every day beyond sixty accrues 20000 cents per day, with the total capped at 1000000 cents; no days late means no fine.

From `FINED`, payment closes the matter: a `DeclarantController` records `payment_cents` equal to `fine_cents` exactly (`ERR_PENALTY_AMOUNT_MISMATCH`) and the violation is `PAID`. Alternatively the respondent — resident or builder, with the acting user matching the respondent (`ERR_FORBIDDEN_ROLE`) — may appeal within thirty days of the fine with an `appeal_reason` (`ERR_APPEAL_WINDOW_EXPIRED` beyond that window), moving the violation to `APPEALED`. Appeal resolution belongs to an `AssociationDirector` other than the director who levied the fine: the resolver's `X-User-ID` must differ from `fined_by_user_id` (`ERR_HEARING_OFFICER_CONFLICT`). The `outcome` must be one of two values — anything else is `ERR_VALIDATION`. `APPEAL_UPHELD` moves the violation to `DISMISSED` and voids `fine_cents` to 0. `APPEAL_DENIED` returns the violation to `FINED`, with `fine_cents` recomputed on the same tiered schedule but with `days_late` measured to the resolution date — accrual resumes through the appeal.

### 3.8. Lifestyle Programming, Sales Operations, and Resident Records

The lifestyle program fills the amenities the developer builds. A `LifestyleCoordinator` proposes a `CommunityEvent` with a `title`, a `venue` of `CLUBHOUSE`, `POOL_DECK`, `EVENT_LAWN`, or `SALES_CENTER`, a `start_at` strictly before `end_at` (an end not after the start is `ERR_VALIDATION`), a `capacity` of at least 1, and a `cost_cents` defaulting to 0; when the cost is positive, `charged_budget_id` is required and names the adopted budget whose events line will absorb the cost. A proposed event starts `PROPOSED` with `confirmed_count` zero.

Scheduling a `PROPOSED` event applies its gates in the §2.9 order. The safety gate runs first: a `CLUBHOUSE`, `POOL_DECK`, or `EVENT_LAWN` venue maps to the amenity type `CLUBHOUSE`, `POOL`, or `EVENT_LAWN` respectively, and that amenity must be `UNDER_CONSTRUCTION` or `OPEN` — a `COMMITTED`, `IN_DESIGN`, or `DELINQUENT` amenity blocks scheduling with `ERR_AMENITY_NOT_OPEN` (residents are never booked into facilities not yet under construction). Next the temporal gate: `start_at` must be at least fourteen days after the logical clock (`ERR_EVENT_LEAD_TIME`). Then overlap: no other `SCHEDULED` event may occupy the same venue over a half-open interval overlap with the new event's start-to-end span — back-to-back adjacency is allowed (`ERR_VENUE_OVERLAP`). Finally the fiscal gate for costed events: the charged budget must be `ADOPTED`, and its `EVENTS_PROGRAMMING` line (zero when the line is absent) minus the `cost_cents` of events already `SCHEDULED` or `COMPLETED` against that budget must leave room for this `cost_cents` (`ERR_EVENT_BUDGET_EXCEEDED`); a cost exactly equal to the remaining room passes. Cancellation is available from `PROPOSED` or `SCHEDULED` and cancels every RSVP in `CONFIRMED` or `WAITLISTED`; the same cascade strikes `SCHEDULED` events automatically when their venue's amenity goes `DELINQUENT`. Events whose `end_at` has passed are swept to `COMPLETED`. Events can be listed by community or filtered by `charged_budget_id`.

Residents book seats through RSVPs. A `HomeownerResident` creates one with an `event_id`, a `resident_id` that must equal their `X-User-ID` (`ERR_FORBIDDEN_ROLE`), and a `party_size` of at least 1, and only against a `SCHEDULED` event (`ERR_INVALID_STATE` otherwise). The RSVP lands `CONFIRMED` when the party fits the event's remaining capacity and `WAITLISTED` otherwise; the event's `confirmed_count` — the sum of `party_size` over its `CONFIRMED` RSVPs — is recomputed on each change. Cancelling a `CONFIRMED` RSVP, by the booking resident or by a `LifestyleCoordinator`, recomputes the count and runs waitlist promotion on strict head-of-line order: the earliest-created `WAITLISTED` RSVP is promoted if its `party_size` fits the freed capacity, and if the head of the line does not fit, nobody is promoted.

The sales center runs alongside. A `LifestyleCoordinator` books a `SalesCenterAppointment` with an `agent_name`, a `visitor_name`, and a `start_at` strictly before `end_at`; at most three `BOOKED` tours may overlap at once, so a fourth overlapping booking is rejected `ERR_TOUR_CAPACITY_REACHED`. Tours are completed or cancelled from `BOOKED`.

Resident records begin at registration: a `LifestyleCoordinator` registers a `Resident` with a `full_name` and an `email` unique within the community (duplicates are `ERR_VALIDATION`), starting as `PROSPECT`. Recording a purchase links the prospect to their homesite `lot_id`: the lot must belong to the same community as the resident (`ERR_RESIDENT_COMMUNITY_MISMATCH`) and must be `UNDER_CONTRACT` or `CLOSED` (`ERR_LOT_NOT_UNDER_CONTRACT`); the resident becomes a `PURCHASER`. Ownership itself arrives only through the closing cascade of §3.4 — a `CLOSED` closing naming the resident as `owner_resident_id` moves them to `OWNER` with `owner_since` set to the `closing_date`, and a `PROSPECT` who was never marked a `PURCHASER` still becomes an `OWNER`, taking the closing's lot as their `lot_id` when they have none. Archiving moves a prospect, purchaser, or owner to `FORMER`.

### 3.9. Notices, Elections, and the Path to Owner Control

Resident communication is statutory, so notices are first-class records. A `LifestyleCoordinator` drafts a `ResidentNotice` with a `notice_type` of `ASSESSMENT_CHANGE`, `TRANSITION_UPDATE`, `AMENITY_DELINQUENCY`, `GENERAL_MEETING`, or `BUDGET_ADOPTION`, a `subject`, a `body`, a scheduled `send_at`, and an optional `effective_date`. Typed links bind the notice to its subject matter: a `BUDGET_ADOPTION` notice must carry a `budget_id`, and an `ASSESSMENT_CHANGE` notice must carry an `assessment_rate_id`; scheduling enforces those requirements (`ERR_VALIDATION`) and requires `send_at` to be strictly after the logical clock (`ERR_SEND_AT_IN_PAST`). Scheduling moves the notice from `DRAFT` to `SCHEDULED`; when the clock reaches `send_at`, the sweep sends it — `sent_at` is set to `send_at` — moving it to `SENT`. A `DRAFT` or `SCHEDULED` notice may be cancelled. Correction works by supersession: superseding a notice creates a fresh `DRAFT` successor from the supplied `subject`, `body`, `send_at`, and optional `effective_date`, carrying over the `notice_type`, `budget_id`, and `assessment_rate_id` of its predecessor and recording it as `supersedes_notice_id`, while the old notice — whether `DRAFT`, `SCHEDULED`, or even `SENT` — becomes `SUPERSEDED`. A superseded notice no longer satisfies the budget-adoption or rate-arm gating of §3.5, even if it had already been sent.

The board's composition tracks the governance ratchet. The five seats created at activation are `DECLARANT_APPOINTED` and `FILLED`. As `transition_stage` advances, owner-elected representation is owed: `DECLARANT_CONTROL` owes zero owner-elected seats, `OWNER_REPRESENTATION` owes one, `PARITY` owes two, and `OWNER_MAJORITY` owes three. On each stage advance, the deficit between the owed count and the current number of `OWNER_ELECTED` seats is made up by converting `DECLARANT_APPOINTED` `FILLED` seats — highest `seat_no` first — into `OWNER_ELECTED` `VACANT` seats: the `seat_class` flips to `OWNER_ELECTED`, the declarant appointee is removed, and `holder_name` and `holder_resident_id` are cleared. When `closed_unit_pct` reaches at least 100.00, every remaining `DECLARANT_APPOINTED` seat converts the same way. Board seats are listed ordered by `seat_no` ascending and can be filtered by community or by `holder_resident_id`.

Filling a vacancy is an electoral process run by an `AssociationDirector`. Calling an election on a `VACANT` `OWNER_ELECTED` seat (`ERR_SEAT_NOT_VACANT` otherwise) — or re-calling one on a `LAPSED` seat — snapshots `eligible_voter_count` as the number of the community's residents in `OWNER` status at that moment and sets the `election_deadline` thirty days out. Certifying the result requires the payload's `votes_cast`, `votes_for`, and `holder_resident_id` to pass three tests: quorum — `votes_cast` at least the ceiling of one fifth of `eligible_voter_count` (twenty percent, with the boundary inclusive; `ERR_QUORUM_NOT_MET` below it); strict majority — `votes_for` strictly more than half of `votes_cast`, so an exact tie fails (`ERR_ELECTION_MAJORITY_NOT_REACHED`); and holder eligibility — the holder must be an `OWNER` resident of the community not already holding a `FILLED` or `ELECTION_CALLED` seat (`ERR_HOLDER_NOT_ELIGIBLE`). Certification records the holder and returns the seat to `FILLED`. If the deadline passes first, the sweep moves the seat to `LAPSED`; late certification is then impossible because the from-state check rejects it with `ERR_INVALID_STATE`.

Statutory turnover is the final act. Once `closed_unit_pct` is at least 100.00 (`ERR_TRANSITION_THRESHOLD_NOT_MET` below it) and all five seats are `OWNER_ELECTED` and `FILLED` (`ERR_TURNOVER_SEATS_NOT_FILLED` otherwise), a `DeclarantExecutive` records turnover: the community moves from `ACTIVE` to `TURNOVER_RECORDED` and `transition_stage` advances to `TURNOVER_COMPLETE`. From that moment, declarant-side governance powers end — budget adoption by an `AssociationDirector`, rate arming by a `DeclarantController`, cap-override approval on the declarant side, and tranche waivers all fail with `ERR_DECLARANT_AUTHORITY_ENDED`, and the owner-side paths of §3.5 take over.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that act on an existing resource — state transitions, computations, cascades — return `200 OK`. The clock endpoint returns `200 OK`. Readers reconstruct full request payloads and side effects from the §3 narratives; this table is the routing and authorization summary only.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Advance the logical clock and run the sweep | PlatformAdmin |
| POST | `/mpc/communities` | Create a community (PLANNING, DECLARANT_CONTROL) | DeclarantExecutive |
| GET | `/mpc/communities` | List communities | Any authenticated role |
| GET | `/mpc/communities/{cid}` | Get one community with computed governance fields | Any authenticated role |
| POST | `/mpc/communities/{cid}/activate` | Activate and seat the five-member declarant board | DeclarantExecutive |
| POST | `/mpc/communities/{cid}/record-turnover` | Record statutory turnover to owner control | DeclarantExecutive |
| GET | `/mpc/communities/{cid}/summary` | Computed governance dashboard | Any authenticated role |
| POST | `/mpc/phases` | Create a phase (PLANNED) | DeclarantExecutive |
| GET | `/mpc/phases` | List phases, optionally by community | Any authenticated role |
| GET | `/mpc/phases/{pid}` | Get one phase | Any authenticated role |
| POST | `/mpc/phases/{pid}/open-sales` | Open a phase for sales (sequencing gate) | DeclarantExecutive |
| POST | `/mpc/phases/{pid}/close-out` | Close out a DELIVERING phase | DeclarantExecutive |
| POST | `/mpc/phases/{pid}/cancel` | Cancel a phase; cascade to lots and agreements | DeclarantExecutive |
| POST | `/mpc/amenities` | Commit an amenity with trigger/deadline | DeclarantExecutive |
| GET | `/mpc/amenities` | List amenities, optionally by community or trigger phase | Any authenticated role |
| GET | `/mpc/amenities/{aid}` | Get one amenity | Any authenticated role |
| POST | `/mpc/amenities/{aid}/start-design` | COMMITTED → IN_DESIGN | DeclarantExecutive |
| POST | `/mpc/amenities/{aid}/start-construction` | IN_DESIGN → UNDER_CONSTRUCTION | DeclarantExecutive |
| POST | `/mpc/amenities/{aid}/open` | UNDER_CONSTRUCTION or DELINQUENT → OPEN | DeclarantExecutive |
| POST | `/mpc/builders` | Credential a builder for a community | DeclarantExecutive |
| GET | `/mpc/builders` | List builders, optionally by community | Any authenticated role |
| GET | `/mpc/builders/{bid}` | Get one builder | Any authenticated role |
| POST | `/mpc/builders/{bid}/reinstate` | Restore GOOD_STANDING after defaults clear | DeclarantExecutive |
| POST | `/mpc/agreements` | Draft a builder lot purchase agreement | DeclarantController |
| GET | `/mpc/agreements` | List agreements by community, builder, or phase | Any authenticated role |
| GET | `/mpc/agreements/{aid}` | Get one agreement | Any authenticated role |
| POST | `/mpc/agreements/{aid}/execute` | Execute a DRAFT agreement (coverage gate) | DeclarantExecutive |
| POST | `/mpc/agreements/{aid}/commence` | EXECUTED → ACTIVE | DeclarantController |
| POST | `/mpc/agreements/{aid}/terminate` | Terminate; open tranches cancelled | DeclarantExecutive |
| POST | `/mpc/agreements/{aid}/amendments` | Supersede the remaining takedown schedule (OCC) | DeclarantController |
| POST | `/mpc/tranches` | Add a tranche to a DRAFT agreement | DeclarantController |
| GET | `/mpc/tranches` | List tranches, optionally by agreement | Any authenticated role |
| GET | `/mpc/tranches/{tid}` | Get one tranche with computed penalty | Any authenticated role |
| POST | `/mpc/tranches/{tid}/cure` | Cure a MISSED tranche with exact penalty | BuilderRep |
| POST | `/mpc/tranches/{tid}/waive` | Waive a MISSED tranche's penalty and deficit | AssociationDirector |
| POST | `/mpc/tranches/{tid}/certify-default` | Certify an uncured default; full cascade | DeclarantExecutive |
| POST | `/mpc/lots` | Plat a lot in a phase | DeclarantExecutive |
| GET | `/mpc/lots` | List lots by phase or community | Any authenticated role |
| GET | `/mpc/lots/{lid}` | Get one lot | Any authenticated role |
| POST | `/mpc/lots/{lid}/offer` | PLATTED → OFFERED | DeclarantExecutive |
| POST | `/mpc/lots/{lid}/withdraw` | OFFERED → WITHDRAWN | DeclarantExecutive |
| POST | `/mpc/closings` | Open escrow on a lot against an agreement | DeclarantController |
| GET | `/mpc/closings` | List closings by agreement, lot, owner, tranche, community | Any authenticated role |
| GET | `/mpc/closings/{clid}` | Get one closing | Any authenticated role |
| POST | `/mpc/closings/{clid}/close` | Record the closing and run the full cascade | DeclarantController |
| POST | `/mpc/closings/{clid}/cancel` | Cancel a PENDING closing | DeclarantController |
| POST | `/mpc/closings/{clid}/rescind` | Rescind a CLOSED closing within thirty days | DeclarantExecutive |
| POST | `/mpc/budgets` | Create a DRAFT budget for a fiscal year | DeclarantController |
| GET | `/mpc/budgets` | List budgets by community or amendment predecessor | Any authenticated role |
| GET | `/mpc/budgets/{bid}` | Get one budget with computed totals | Any authenticated role |
| POST | `/mpc/line-items` | Add a line item to a DRAFT budget | DeclarantController |
| GET | `/mpc/line-items` | List line items, optionally by budget | Any authenticated role |
| GET | `/mpc/line-items/{liid}` | Get one line item | Any authenticated role |
| POST | `/mpc/budgets/{bid}/propose` | DRAFT → PROPOSED | DeclarantController |
| POST | `/mpc/budgets/{bid}/adopt` | Adopt; ADOPTED pre-parity, PENDING_RATIFICATION after | AssociationDirector, OwnerDirector |
| POST | `/mpc/budgets/{bid}/ratify` | Ratify a PENDING_RATIFICATION budget | OwnerDirector |
| POST | `/mpc/budgets/{bid}/reject` | Reject a PROPOSED or PENDING_RATIFICATION budget | AssociationDirector |
| POST | `/mpc/budgets/{bid}/revise` | REJECTED → DRAFT | DeclarantController |
| POST | `/mpc/budgets/{bid}/amendments` | Create the successor DRAFT amendment (OCC) | DeclarantController |
| POST | `/mpc/assessment-rates` | Compute the annual rate from an ADOPTED budget | DeclarantController |
| GET | `/mpc/assessment-rates` | List rates by community, budget, or prior rate | Any authenticated role |
| GET | `/mpc/assessment-rates/{rid}` | Get one assessment rate | Any authenticated role |
| POST | `/mpc/assessment-rates/{rid}/approve-cap-override` | Approve a statutory-cap override | AssociationDirector, OwnerDirector |
| POST | `/mpc/assessment-rates/{rid}/ratify-cap-override` | Ratify an approved override | OwnerDirector |
| POST | `/mpc/assessment-rates/{rid}/arm` | Arm a CALCULATED rate | DeclarantController, OwnerDirector |
| POST | `/mpc/districts` | Create the community's reimbursement district | DeclarantController |
| GET | `/mpc/districts` | List districts, optionally by community | Any authenticated role |
| GET | `/mpc/districts/{did}` | Get one district with computed balances | Any authenticated role |
| POST | `/mpc/advances` | Record an infrastructure advance | DeclarantController |
| GET | `/mpc/advances` | List advances, optionally by district | Any authenticated role |
| GET | `/mpc/advances/{aid}` | Get one advance | Any authenticated role |
| POST | `/mpc/levies` | Plan an annual district levy | DeclarantController |
| GET | `/mpc/levies` | List levies, optionally by district | Any authenticated role |
| GET | `/mpc/levies/{lid}` | Get one levy | Any authenticated role |
| POST | `/mpc/levies/{lid}/collect` | Collect a PLANNED levy into district funds | DeclarantController |
| POST | `/mpc/payments` | Request a reimbursement payment | DeclarantController |
| GET | `/mpc/payments` | List payments, optionally by district | Any authenticated role |
| GET | `/mpc/payments/{pid}` | Get one payment | Any authenticated role |
| POST | `/mpc/payments/{pid}/certify` | Audit-certify: compound interest, FIFO waterfall | AssociationDirector |
| POST | `/mpc/payments/{pid}/pay` | Disburse a CERTIFIED payment | DeclarantController |
| POST | `/mpc/payments/{pid}/reject` | Reject; CERTIFIED rejection unwinds allocations | AssociationDirector |
| POST | `/mpc/applications` | Submit a design review application | BuilderRep, HomeownerResident |
| GET | `/mpc/applications` | List applications by community, lot, or applicant | Any authenticated role |
| GET | `/mpc/applications/{aid}` | Get one application | Any authenticated role |
| POST | `/mpc/applications/{aid}/begin-review` | Claim an application for review | DesignReviewer |
| POST | `/mpc/applications/{aid}/approve` | Approve the application under review | DesignReviewer |
| POST | `/mpc/applications/{aid}/approve-with-conditions` | Conditionally approve with conditions text | DesignReviewer |
| POST | `/mpc/applications/{aid}/deny` | Deny the application under review | DesignReviewer |
| POST | `/mpc/applications/{aid}/resubmit` | Resubmit a DENIED application (round fee) | BuilderRep, HomeownerResident |
| POST | `/mpc/applications/{aid}/verify-conditions` | Verify conditions → APPROVED | DesignReviewer |
| POST | `/mpc/applications/{aid}/record-construction-start` | Record construction start; prevents expiry | BuilderRep, HomeownerResident |
| POST | `/mpc/applications/{aid}/withdraw` | Withdraw a SUBMITTED or DENIED application | BuilderRep, HomeownerResident |
| POST | `/mpc/violations` | Report a covenant violation against a lot | DesignReviewer, AssociationDirector |
| GET | `/mpc/violations` | List violations by community, lot, or respondent | Any authenticated role |
| GET | `/mpc/violations/{vid}` | Get one violation with computed days late and fine | Any authenticated role |
| POST | `/mpc/violations/{vid}/send-notice` | REPORTED → NOTICE_SENT; sets the cure deadline | DesignReviewer |
| POST | `/mpc/violations/{vid}/record-cure` | NOTICE_SENT → CURED | DesignReviewer |
| POST | `/mpc/violations/{vid}/escalate` | NOTICE_SENT → ESCALATED after the deadline | DesignReviewer |
| POST | `/mpc/violations/{vid}/schedule-hearing` | ESCALATED → HEARING_SCHEDULED | AssociationDirector |
| POST | `/mpc/violations/{vid}/levy-fine` | HEARING_SCHEDULED → FINED; tiered accrual | AssociationDirector |
| POST | `/mpc/violations/{vid}/record-payment` | FINED → PAID with exact amount | DeclarantController |
| POST | `/mpc/violations/{vid}/appeal` | Appeal a FINED violation within thirty days | HomeownerResident, BuilderRep |
| POST | `/mpc/violations/{vid}/resolve-appeal` | Resolve an appeal; resolver differs from levier | AssociationDirector |
| POST | `/mpc/events` | Propose a lifestyle event | LifestyleCoordinator |
| GET | `/mpc/events` | List events by community or charged budget | Any authenticated role |
| GET | `/mpc/events/{eid}` | Get one event | Any authenticated role |
| POST | `/mpc/events/{eid}/schedule` | Schedule a PROPOSED event (four gates) | LifestyleCoordinator |
| POST | `/mpc/events/{eid}/cancel` | Cancel; RSVPs cascade | LifestyleCoordinator |
| POST | `/mpc/rsvps` | RSVP to a SCHEDULED event | HomeownerResident |
| GET | `/mpc/rsvps` | List RSVPs by event or resident | Any authenticated role |
| GET | `/mpc/rsvps/{rid}` | Get one RSVP | Any authenticated role |
| POST | `/mpc/rsvps/{rid}/cancel` | Cancel; head-of-line waitlist promotion runs | HomeownerResident, LifestyleCoordinator |
| POST | `/mpc/appointments` | Book a sales-center tour (max three overlapping) | LifestyleCoordinator |
| GET | `/mpc/appointments` | List appointments, optionally by community | Any authenticated role |
| GET | `/mpc/appointments/{aid}` | Get one appointment | Any authenticated role |
| POST | `/mpc/appointments/{aid}/cancel` | BOOKED → CANCELLED | LifestyleCoordinator |
| POST | `/mpc/appointments/{aid}/complete` | BOOKED → COMPLETED | LifestyleCoordinator |
| POST | `/mpc/residents` | Register a prospect resident | LifestyleCoordinator |
| GET | `/mpc/residents` | List residents by community or lot | Any authenticated role |
| GET | `/mpc/residents/{rid}` | Get one resident | Any authenticated role |
| POST | `/mpc/residents/{rid}/record-purchase` | PROSPECT → PURCHASER, linking the homesite | LifestyleCoordinator |
| POST | `/mpc/residents/{rid}/archive` | Archive a resident (→ FORMER) | LifestyleCoordinator |
| POST | `/mpc/notices` | Draft a resident notice | LifestyleCoordinator |
| GET | `/mpc/notices` | List notices by community, budget, rate, or predecessor | Any authenticated role |
| GET | `/mpc/notices/{nid}` | Get one notice | Any authenticated role |
| POST | `/mpc/notices/{nid}/schedule` | Schedule a DRAFT notice | LifestyleCoordinator |
| POST | `/mpc/notices/{nid}/cancel` | Cancel a DRAFT or SCHEDULED notice | LifestyleCoordinator |
| POST | `/mpc/notices/{nid}/supersede` | Issue a corrected notice; old one SUPERSEDED | LifestyleCoordinator |
| GET | `/mpc/board-seats` | List board seats by community or holder, by seat_no | Any authenticated role |
| GET | `/mpc/board-seats/{sid}` | Get one board seat | Any authenticated role |
| POST | `/mpc/board-seats/{sid}/call-election` | Call an election for a VACANT or LAPSED seat | AssociationDirector |
| POST | `/mpc/board-seats/{sid}/certify-election` | Certify election results (quorum, majority, eligibility) | AssociationDirector |

## 5. Error Code Catalogue

Trigger conditions for each error live in the §2 and §3 narratives; this catalogue fixes only the identifier and status.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN_ROLE` | 403 Forbidden |
| `ERR_VALIDATION` | 400 Bad Request |
| `ERR_COMMUNITY_NOT_FOUND` | 404 Not Found |
| `ERR_PHASE_NOT_FOUND` | 404 Not Found |
| `ERR_AMENITY_NOT_FOUND` | 404 Not Found |
| `ERR_BUILDER_NOT_FOUND` | 404 Not Found |
| `ERR_AGREEMENT_NOT_FOUND` | 404 Not Found |
| `ERR_TRANCHE_NOT_FOUND` | 404 Not Found |
| `ERR_LOT_NOT_FOUND` | 404 Not Found |
| `ERR_CLOSING_NOT_FOUND` | 404 Not Found |
| `ERR_BUDGET_NOT_FOUND` | 404 Not Found |
| `ERR_LINE_ITEM_NOT_FOUND` | 404 Not Found |
| `ERR_RATE_NOT_FOUND` | 404 Not Found |
| `ERR_DISTRICT_NOT_FOUND` | 404 Not Found |
| `ERR_ADVANCE_NOT_FOUND` | 404 Not Found |
| `ERR_LEVY_NOT_FOUND` | 404 Not Found |
| `ERR_PAYMENT_NOT_FOUND` | 404 Not Found |
| `ERR_APPLICATION_NOT_FOUND` | 404 Not Found |
| `ERR_VIOLATION_NOT_FOUND` | 404 Not Found |
| `ERR_EVENT_NOT_FOUND` | 404 Not Found |
| `ERR_RSVP_NOT_FOUND` | 404 Not Found |
| `ERR_APPOINTMENT_NOT_FOUND` | 404 Not Found |
| `ERR_RESIDENT_NOT_FOUND` | 404 Not Found |
| `ERR_NOTICE_NOT_FOUND` | 404 Not Found |
| `ERR_BOARD_SEAT_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_COMMUNITY_NOT_ACTIVE` | 409 Conflict |
| `ERR_PHASE_NOT_OPEN_FOR_SALES` | 409 Conflict |
| `ERR_AGREEMENT_NOT_ACTIVE` | 409 Conflict |
| `ERR_LOT_NOT_OFFERED` | 409 Conflict |
| `ERR_LOT_NOT_UNDER_CONTRACT` | 409 Conflict |
| `ERR_BUILDER_NOT_IN_GOOD_STANDING` | 409 Conflict |
| `ERR_OUTSTANDING_COMPLIANCE_DEFAULTS` | 409 Conflict |
| `ERR_CLOSEOUT_BLOCKED` | 409 Conflict |
| `ERR_CLOSINGS_PENDING` | 409 Conflict |
| `ERR_BUDGET_EMPTY` | 409 Conflict |
| `ERR_BUDGET_NOT_ADOPTED` | 409 Conflict |
| `ERR_NOTICE_NOT_SENT` | 409 Conflict |
| `ERR_TRANCHE_NOT_CURABLE` | 409 Conflict |
| `ERR_CURE_WINDOW_OPEN` | 409 Conflict |
| `ERR_SEAT_NOT_VACANT` | 409 Conflict |
| `ERR_REVIEW_ROUNDS_EXHAUSTED` | 409 Conflict |
| `ERR_DECLARANT_AUTHORITY_ENDED` | 409 Conflict |
| `ERR_SUBSIDY_NOT_AVAILABLE` | 409 Conflict |
| `ERR_NO_PRIOR_RATE` | 409 Conflict |
| `ERR_TRANSITION_THRESHOLD_NOT_MET` | 409 Conflict |
| `ERR_TURNOVER_SEATS_NOT_FILLED` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_AMENITY_NOT_OPEN` | 409 Conflict |
| `ERR_EVENT_LEAD_TIME` | 422 Unprocessable Entity |
| `ERR_NOTICE_LEAD_TIME` | 422 Unprocessable Entity |
| `ERR_RESCISSION_WINDOW_EXPIRED` | 422 Unprocessable Entity |
| `ERR_APPEAL_WINDOW_EXPIRED` | 422 Unprocessable Entity |
| `ERR_SEND_AT_IN_PAST` | 422 Unprocessable Entity |
| `ERR_PHASE_SEQUENCE_BLOCKED` | 409 Conflict |
| `ERR_DUPLICATE_FISCAL_YEAR` | 409 Conflict |
| `ERR_DUPLICATE_ASSESSMENT_YEAR` | 409 Conflict |
| `ERR_DUPLICATE_DISTRICT` | 409 Conflict |
| `ERR_DUPLICATE_TRANCHE_NO` | 409 Conflict |
| `ERR_VENUE_OVERLAP` | 409 Conflict |
| `ERR_TOUR_CAPACITY_REACHED` | 409 Conflict |
| `ERR_REVIEWER_CONFLICT` | 403 Forbidden |
| `ERR_ADOPTER_CANNOT_RATIFY` | 403 Forbidden |
| `ERR_HEARING_OFFICER_CONFLICT` | 403 Forbidden |
| `ERR_QUORUM_NOT_MET` | 409 Conflict |
| `ERR_ELECTION_MAJORITY_NOT_REACHED` | 409 Conflict |
| `ERR_LOT_PHASE_MISMATCH` | 422 Unprocessable Entity |
| `ERR_APPLICANT_IDENTITY_INVALID` | 422 Unprocessable Entity |
| `ERR_RESPONDENT_IDENTITY_INVALID` | 422 Unprocessable Entity |
| `ERR_FISCAL_YEAR_MISMATCH` | 422 Unprocessable Entity |
| `ERR_RESIDENT_COMMUNITY_MISMATCH` | 422 Unprocessable Entity |
| `ERR_TRANCHE_COVERAGE_MISMATCH` | 422 Unprocessable Entity |
| `ERR_HOLDER_NOT_ELIGIBLE` | 422 Unprocessable Entity |
| `ERR_INSUFFICIENT_DISTRICT_FUNDS` | 402 Payment Required |
| `ERR_PAYMENT_EXCEEDS_OBLIGATION` | 402 Payment Required |
| `ERR_ASSESSMENT_CAP_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_EVENT_BUDGET_EXCEEDED` | 402 Payment Required |
| `ERR_PENALTY_AMOUNT_MISMATCH` | 402 Payment Required |
