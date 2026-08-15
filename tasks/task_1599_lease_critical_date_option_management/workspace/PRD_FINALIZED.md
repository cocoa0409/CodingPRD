# Lease Critical Dates API — Product Requirements Document

## 1. Introduction

Corporate real estate departments live and die by dates. Every lease in a portfolio carries an inventory of tenant options — renewals, expansions, early terminations, and rights of first refusal — and each option can be exercised only inside a contractual notice window. A notice delivered one day late forfeits the option; a renewal negotiated too late closes after expiration; a tenant who simply stays put rolls into costly holdover. This document specifies the Lease Critical Dates API, the system of record for those obligations across a portfolio: it models the option inventory and its notice windows, drives a tiered reminder cascade to asset managers and brokers, administers fair-market rent determination with arbitration, governs exercise notice delivery and acknowledgment, prices holdover tenancy, analyzes the consequences of missed options, and reports portfolio-level expiration laddering and negotiation-timeline compliance.

Because nearly every rule in this domain is temporal, the service runs on a logical clock rather than wall time. Transitions that real leases suffer silently at midnight — windows opening, options lapsing, tenancies tipping into holdover — are here explicit, observable consequences of clock advancement, each with its own ledger postings and reminder side effects. Four audiences use the API: back-office platform administrators who own setup and the clock, asset managers on the tenant side, external brokers who physically deliver notices, and landlord's counsel who acknowledge notices, negotiate the other side of every amendment, and render arbitration decisions.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. The recognized role values are exactly `PlatformAdmin`, `AssetManager`, `Broker`, and `LandlordCounsel`. A request missing either header, or carrying a role value outside that set, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose authenticated role is not permitted for the target endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403).

The identity behind `X-User-ID` differs by role. When `X-User-Role` is `PlatformAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it but never compares it to any entity's `id`. When `X-User-Role` is `AssetManager`, `X-User-ID` is the `id` of the acting `Contact` whose `contact_kind` is `ASSET_MANAGER`; when `X-User-Role` is `Broker`, it is the `id` of the acting `Contact` whose `contact_kind` is `BROKER`; when `X-User-Role` is `LandlordCounsel`, it is the `id` of the acting `Contact` whose `contact_kind` is `LANDLORD_COUNSEL`. For these three entity-backed roles, ownership checks on any resource that references a contact compare the resource's foreign-key field to `X-User-ID`. This is what makes segregation-of-duties and delivery-ownership checks possible: the system knows which contact proposed an amendment and refuses to let that same contact agree to it.

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

### 2.3. Pagination

List endpoints paginate through the `limit` and `offset` query parameters. `limit` specifies the maximum number of items returned: it defaults to 10 when omitted, accepts a minimum of 1, and is capped at a maximum of 100. `offset` specifies how many items to skip and defaults to 0. Unless otherwise specified, every list endpoint returns resources sorted by `created_at` in ascending order. The `meta` object of a list response carries `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. The Logical Clock and Scheduled Sweeps

The service keeps its own logical clock. Before any operator intervention the clock reads exactly 2026-08-01T00:00:00Z, and it never falls back to wall time. A `PlatformAdmin`-only, test-driving capability pins the clock to a supplied `to_iso8601` instant. Every advance runs the full sweep battery as one observable event: due reminders fire, options past their notice windows lapse, leases approaching expiration roll into `EXPIRING`, leases past expiration without renewal roll into `HOLDOVER` or `EXPIRED`, undisputed provisional assessments older than fifteen days finalize, arbitration cases past their submission deadline freeze, and accrued holdover rent is recomputed on every lease sitting in `HOLDOVER`. Each advance returns a freshly created `ClockEvent` recording the pinned value in `set_to` plus three audit arrays — `fired_reminder_ids`, `lapsed_option_ids`, and `holdover_lease_ids` — so the caller can see exactly which resources the advance touched. Because a clock advance creates a new resource, it answers 201.

### 2.5. Common Resource Properties

Portfolios, leases, contacts, options, market-rate assessments, arbitration cases, exercise notices, reminders, and amendments all share four system-managed properties:

- `id` (string): a server-minted UUID with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits, set once at creation.
- `updated_at` (string): an ISO 8601 UTC timestamp refreshed on every mutation of the resource.
- `version` (integer): a system-managed integer that increments by one with every mutation, and which anchors the optimistic concurrency rules of §2.7.

Two resources are append-only records and deliberately carry less. A `LedgerEntry` and a `ClockEvent` each expose `id` and `created_at` only; `updated_at` and `version` are absent from both, because neither is ever modified after creation.

### 2.6. Nested Resource Retrieval and Referential Scope

The API is deeply nested: a portfolio contains leases and contacts; a lease contains options, amendments, and a ledger; an option contains notices, assessments, and reminders; an assessment carries at most one arbitration case. Path identifiers are validated strictly left to right, and the request is rejected with `ERR_NOT_FOUND` (HTTP 404) at the first identifier that does not exist or is not nested beneath its declared parent — later segments are never examined. Within nested paths the identifiers are `pid` for the portfolio, `lid` for the lease, `oid` for the option, `nid` for the notice, `mid` for the assessment, `aid` for the amendment, and `cid` for the contact; the flat read aliases described below use a bare `id`.

Foreign keys supplied in request bodies are checked against the enclosing scope. A referenced contact must belong to the same portfolio as the resource being acted on, and an amendment's `supersedes_amendment_id` must name an amendment of the same lease. A body key that resolves outside its scope is rejected with `ERR_FK_SCOPE_VIOLATION` (HTTP 422).

Alongside the nested routes, a flat reverse-reachability surface exposes the same resources at root level for reading: a lease by bare `id`; a cross-portfolio lease list filterable by `status` or `active_amendment_id`; an option, an assessment, a contact, or an amendment by `id`; a cross-lease amendment list filterable by `status`, `kind`, or `supersedes_amendment_id`; and flat child listings — a lease's options, amendments, and ledger; an option's assessments, notices, reminders, and sourced ledger entries; an assessment's arbitration case and sourced ledger entries; and the reminders addressed to a contact. Aliases are read-only views over the same resources; every write travels the nested hierarchy.

### 2.7. Optimistic Concurrency Control

Five write operations are guarded by optimistic concurrency against a parent entity's `version`: the client echoes the version it last observed, and a mismatch means the client's view of the parent is stale. Delivering an exercise notice — first delivery or re-delivery — requires `expected_lease_version` equal to the lease's current `version`; a mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412), since activation, amendment activity, or a prior notice may have advanced the lease since the client last read it. Withdrawing an option carries the same `expected_lease_version` requirement and the same `ERR_STALE_VERSION` rejection. Submitting a market-rate assessment requires `expected_option_version` equal to the option's current `version`, rejected on mismatch with `ERR_STALE_VERSION` (HTTP 412) — superseding a provisional assessment itself advances the option's version, so a second submitter working from an older read cannot silently overwrite the first. Proposing an amendment and executing an amendment each require `expected_lease_version` matching the lease's current `version`, with `ERR_STALE_VERSION` on mismatch. No other endpoint accepts a version field; reads, countering, re-proposing, agreeing, abandoning, delivering, rejecting, acknowledging, deciding, activating, and vacating take none.

### 2.8. Monetary Representation, Rounding, and Calendar Granularity

All money is integer cents. Rents are expressed as annual cents per rentable square foot; fees, penalties, awards, and ledger amounts are plain cents. Where a calculation produces a fraction of a cent, the result rounds half up to the nearest whole cent at exactly the step the calculation specifies — the holdover accrual of §3.8 pins its rounding order explicitly, and an implementation that defers rounding to a single grand-total step is non-conformant. Calendar fields such as commencement, expiration, notice-window bounds, and effective dates are date-only values represented at UTC midnight, and all window arithmetic is evaluated at date granularity in UTC.

### 2.9. The Lease Ledger

Every financial consequence of the option lifecycle posts to the owning lease's ledger as a `LedgerEntry`, whose `lease_id` identifies the account it posts to. The `entry_kind` is one of four values: `OPTION_FEE` for a fee due on exercise, `MISSED_OPTION_PENALTY` for a deposit forfeiture or contractual penalty when an option lapses unexercised, `ARBITRATION_AWARD_ADJUSTMENT` for the true-up between an arbitration award and a provisional rent, and `AMENDMENT_SETTLEMENT` for the final holdover settlement collected when a settlement amendment executes. Each entry carries a signed `amount_cents` — positive means receivable from the tenant — the `effective_date` it accrues to, and, when a specific instrument caused it, a `source_option_id` or `source_assessment_id` pointing at the origin; both are null when not applicable. Entries post at the moment their triggering event occurs. A lease's ledger can be listed with an optional `entry_kind` filter, and per-option or per-assessment views of sourced entries are available through the flat aliases.

### 2.10. Validation Order of Evaluation

Requests are validated in a fixed priority order so that failures surface deterministically rather than masking one another. Authentication comes first (missing or unknown headers yield `ERR_UNAUTHENTICATED`), then role permission for the endpoint (`ERR_FORBIDDEN`), then left-to-right path existence and nesting (`ERR_NOT_FOUND`), then body foreign-key scope (`ERR_FK_SCOPE_VIOLATION`), then state admissibility of the requested transition (`ERR_INVALID_STATE`). Only after those five gates do endpoint-specific business rules run, and where several share one endpoint they evaluate in ascending priority: on notice creation, notice-window membership before duplicate-notice detection before the stale-version check; on amendment proposal, negotiation exclusivity before the stale-version check; on amendment execution, segregation of duties before the stale-version check before the ladder guard before holdover presence; on option registration, temporal order before rate-term coherence; on assessment submission, assessment shape before the stale-version check; on a dispute, option state before dispute-window timeliness; on activation, the lease's state and term preconditions before the ladder guard. Independently of this ordering, a malformed body — a missing required field, a wrong-typed value, or an enum outside its declared set — is rejected with `ERR_VALIDATION` (HTTP 400).

## 3. Business Logic & Workflows

### 3.1. Portfolio Setup and the Contact Roster

A `PlatformAdmin` opens a portfolio by supplying a display `name`, a reporting `region`, and `laddering_max_pct_per_year` — the maximum share, as a whole percentage from 0 to 100, of the portfolio's rentable square footage whose lease expirations may fall in any single calendar year before the portfolio's posture trips. A fresh portfolio reports `total_active_square_feet` of zero, a `posture` of `LADDER_OK`, and a null `posture_year`. The portfolio list is paginated and filterable by `region`.

Contacts are the people the system notifies, and — through the entity-backed identities of §2.1 — the actors behind three of the four roles. Registration takes a `full_name`, an `email` that must be unique within the portfolio, a `contact_kind` of `ASSET_MANAGER`, `BROKER`, or `LANDLORD_COUNSEL`, and optionally `is_active`, which defaults to true; each contact is bound to its portfolio by `portfolio_id`. Inactive contacts receive no new reminders. A contact's `full_name`, `email`, or `is_active` may be updated later; flipping `is_active` from true to false cascades immediately, canceling every still-`PENDING` reminder addressed to that contact. The contact list filters by `contact_kind` and `is_active`.

### 3.2. Lease Onboarding, Activation, and the Expiration Ladder

An `AssetManager` (or `PlatformAdmin`) records a lease under its portfolio — the lease's `portfolio_id` — with a `premises_label` identifying the building, floor, or suite; the covered `rentable_square_feet`, which must be greater than zero; the current `base_rent_cents_per_rsf_year`, also greater than zero; the `commencement_date`; and the `expiration_date`, which must fall strictly after commencement or registration is rejected with `ERR_TEMPORAL_ORDER`. Holdover pricing travels on the lease itself: `holdover_tier1_pct` (typically 150) is the percentage of then-current base rent charged during the first holdover tier, `holdover_tier2_pct` (typically 200) applies from the second tier onward, and `holdover_tier1_days` sets the first tier's length in days, defaulting to 90 when omitted. A new lease starts in `DRAFT` with `accrued_holdover_rent_cents` at zero and `active_amendment_id` null.

Activation is the `AssetManager`'s explicit act, allowed only when the term has actually begun: the `commencement_date` must be on or before the current logical clock date and the `expiration_date` strictly after it, with violations rejected as `ERR_INVALID_STATE`. Activating moves the lease `DRAFT` → `ACTIVE`, increments the lease's `version`, and recomputes the portfolio's `total_active_square_feet`, which is the sum of `rentable_square_feet` across the portfolio's leases in `ACTIVE`, `EXPIRING`, or `HOLDOVER`. The lease list of a portfolio filters by `status`.

The **expiration ladder** is the portfolio's concentration report. For each calendar year from the current clock year through the latest expiration year, the system sums the `rentable_square_feet` of leases in `ACTIVE`, `EXPIRING`, or `HOLDOVER` whose `expiration_date` falls in that year, then expresses each year's expiring footage as a whole percentage of `total_active_square_feet`, rounded half up. When any year's exposure strictly exceeds `laddering_max_pct_per_year`, the portfolio's `posture` reads `LADDER_STRESSED` and `posture_year` names the earliest breaching calendar year; a year whose exposure equals the cap exactly does not trip the posture, and when `total_active_square_feet` is zero the posture is `LADDER_OK`. A computed read exposes the per-year ladder together with the derived `posture` and `posture_year`, and both fields ride along on every portfolio read. The ladder doubles as an advisory gate: a caller who passes `enforce_ladder` as true on activation asks the system to reject the operation with `ERR_LADDER_BREACH` when the activation would push the portfolio into `LADDER_STRESSED`; the flag is off by default, and when supplied it is evaluated only after the lease's state and term preconditions have passed.

The approach of expiration is itself a tracked event. When the logical clock reaches the day 180 days before a lease's `expiration_date` while remaining before that date, the lease moves `ACTIVE` → `EXPIRING` automatically, its `version` increments, and — as the first cascade hop — each of its options still `AVAILABLE` whose notice window contains the clock date opens to `WINDOW_OPEN`, which in turn spawns each such option's reminder cascade (§3.4) as the second hop.

When the tenant leaves on time, an `AssetManager` records the vacatur; to take effect, the record must be made at or before the `expiration_date`. At the next clock sweep past expiration the lease then moves from `ACTIVE` or `EXPIRING` to `EXPIRED` instead of rolling into holdover: its unexercised options become `SUPERSEDED` — not `LAPSED`, so no missed-option penalty posts for an on-time departure — their `PENDING` reminders are `CANCELED`, the lease's `version` increments, and portfolio totals recompute.

### 3.3. Option Registration and Notice Windows

Options are the heart of the inventory. An `AssetManager` registers an option on a lease — recorded on the row as `lease_id` — with an `option_type` of `RENEWAL`, `EXPANSION`, `TERMINATION`, or `ROFR`; a `notice_window_open_date` and a `notice_window_close_date` bracketing the period in which exercise notice may be delivered; and a `target_commencement_date`, which carries the start date of the new term for `RENEWAL` and `EXPANSION`, the early-termination effective date for `TERMINATION`, and the matching-offer response deadline for `ROFR`. Both window bounds are inclusive: a notice dated exactly on the close date is timely, while one dated the day after lapses the option. Registration enforces temporal order first — the close date must fall on or after the open date, and an inversion is rejected with `ERR_TEMPORAL_ORDER`.

Pricing terms are declared at registration and checked for coherence after the temporal check. `rate_determination` is `FIXED` or `FAIR_MARKET` and is meaningful only for `RENEWAL` and `EXPANSION` options; a `FIXED` option must carry a positive `fixed_rent_cents_per_rsf_year`, a `FAIR_MARKET` option must not carry one at all, and `TERMINATION` or `ROFR` options follow fixed-rate semantics with their exercise terms carried on the option row — any incoherence is rejected with `ERR_RATE_TERMS_INCOHERENT`. For a `RENEWAL`, `extension_years` sets the renewal term length in whole years from one to ten; for the other types it is ignored and stored as null. `exercise_fee_cents` is the non-refundable fee payable on exercise — customary on `TERMINATION` options but permitted on any type when the lease so provides — and defaults to zero. `missed_option_penalty_cents` is the amount forfeited when the option lapses unexercised, likewise defaulting to zero.

A new option starts `AVAILABLE`. When a clock advance lands the date inside its notice window while the parent lease is `ACTIVE` or `EXPIRING`, the option moves `AVAILABLE` → `WINDOW_OPEN` and spawns its reminder cascade. The option list of a lease filters by `status` and `option_type`.

### 3.4. The Reminder Cascade

The moment an option enters `WINDOW_OPEN`, the system builds its reminder cascade: for every contact of the portfolio whose `is_active` is true at that moment, five `PENDING` reminders are created — one per `tier`, named `T90`, `T60`, `T30`, `T7`, and `T0` for the number of days before the `notice_window_close_date` at which each is scheduled. Every reminder row carries the option's `option_id` and the recipient's `contact_id`.

Each reminder's `scheduled_for` begins as the close date minus its tier's offset in days, then rolls forward over weekends — a Saturday date shifts two days forward and a Sunday date one — and lands at 09:00:00 UTC. Roll-forward can push a `T0` reminder past the close date itself; that is intended, because the `T0` reminder serves as a lapse alarm rather than a deadline.

Firing is a clock-sweep behavior. On each advance, every `PENDING` reminder whose `scheduled_for` is at or before the clock transitions to `SENT` with `sent_at` stamped, provided its option is not `IN_ARBITRATION` and its recipient contact remains active. When a single advance crosses several tiers at once, reminders fire in chronological order of `scheduled_for`, earliest first; ties on the same timestamp break by tier severity, `T0` first, then `T7`, `T30`, `T60`, and `T90` last; any remaining ties break by the recipient contact's `created_at`, earliest first. Reminder identifiers are never consulted for ordering. A reminder is `CANCELED` when its option reaches `EXERCISED`, `LAPSED`, `WITHDRAWN`, or `SUPERSEDED`, or when its recipient contact is deactivated. An option's reminder list filters by `status`, `tier`, or `contact_id`, and a flat alias lists every reminder addressed to a given contact.

### 3.5. Exercise Notices: Delivery, Acknowledgment, and Exercise Completion

Delivering an exercise notice is the `AssetManager`'s act. The payload names a `delivery_method` of `CERTIFIED_MAIL`, `COURIER`, `PERSONAL_DELIVERY`, or `EMAIL_IF_PERMITTED` and carries the optimistic-concurrency token `expected_lease_version`. Four gates guard the first notice, evaluated in order: the parent lease must be `ACTIVE` or `EXPIRING` (else `ERR_INVALID_STATE`); the current clock date must fall within the notice window, both bounds inclusive (else `ERR_NOTICE_WINDOW_CLOSED`); no other notice on the option may be open in `SENT` or `DELIVERED` (else `ERR_NOTICE_ALREADY_OPEN`); and the lease version token must match (else `ERR_STALE_VERSION`). Success creates the `ExerciseNotice` — bound to the option through `option_id` — in `SENT` with `sent_at` stamped, moves the option from `AVAILABLE` or `WINDOW_OPEN` to `NOTICE_SENT`, and increments the lease's `version`. An option's notice history is listable and filterable by `status`.

Physical delivery is the `Broker`'s confirmation, moving the notice `SENT` → `DELIVERED` and stamping `delivered_at`. Ownership is enforced: the acting broker's identity must match the broker contact registered for the parent portfolio, so a broker of another portfolio cannot confirm this delivery. A broker who cannot deliver — a bad address, a refusal — instead marks the notice `SENT` → `REJECTED`, supplying a non-empty `rejection_reason`.

Rejection is not the end of the option. While the clock date remains on or before the `notice_window_close_date` and every prior notice on the option sits in `VOID` or `REJECTED`, the `AssetManager` may deliver a fresh notice under the same lease-version guard; the previously rejected notice becomes `VOID`, a new notice is created in `SENT`, and the lease's `version` increments again.

Receipt is acknowledged by `LandlordCounsel`, moving the notice `DELIVERED` → `ACKNOWLEDGED` and stamping `acknowledged_at`. An acknowledgment attempted after the `notice_window_close_date` is rejected with `ERR_ACK_AFTER_WINDOW`, and the exercise cannot complete.

Acknowledgment completes the exercise — the first cascade hop moves the option `NOTICE_SENT` → `EXERCISED` — provided the pricing gate has also cleared: a `FAIR_MARKET` option requires a market-rate assessment in `FINAL`, whether finalized unchallenged or decided by arbitration, and the acknowledgment must have occurred on or before the close date. Completion stamps `exercised_at`; fixes `determined_rent_cents_per_rsf_year`, with a `FIXED` option copying its `fixed_rent_cents_per_rsf_year` and a `FAIR_MARKET` option copying the `FINAL` assessment's `determined_rent_cents`; posts an `OPTION_FEE` ledger entry when `exercise_fee_cents` is positive; and cancels the option's remaining `PENDING` reminders.

The second cascade hop depends on the option type. An exercised `RENEWAL` whose `target_commencement_date` has been reached moves the lease to `RENEWED`: a successor lease row is auto-created in `DRAFT` with `commencement_date` equal to the option's target date, `expiration_date` equal to the target date extended by `extension_years` years, and base rent equal to the option's `determined_rent_cents_per_rsf_year`; every other non-terminal option on the old lease becomes `SUPERSEDED`, their `PENDING` reminders are `CANCELED`, and portfolio totals recompute. An exercised `TERMINATION` whose target date has been reached moves the lease to `TERMINATED`, with the same supersession of other non-terminal options, the same reminder cancellations, and the same recompute. Exercising an `EXPANSION` or `ROFR` option completes at the option level and does not by itself move the lease's lifecycle state.

### 3.6. Fair-Market Assessment and Baseball Arbitration

Rent on a `FAIR_MARKET` option is set by assessment. An `AssetManager` submits one under the optimistic-concurrency token `expected_option_version`, choosing a `method`. With `COMPARABLE_AVERAGE`, the payload carries `comparable_rents_cents` — three to seven comparable annual rents in cents per square-foot-year, every one positive — and the provisional rent is their arithmetic mean, rounded half up to a whole cent. With `PSF_REGRESSION`, the payload instead carries a positive `regression_base_cents` plus `regression_adjustments`, a possibly empty list of signed cent adjustments such as floor premiums or TI amortization; the provisional rent is the base plus the sum of the adjustments, floored at one cent so it can never come out zero or negative, with no mean and no rounding step. The two shapes may not be mixed — a comparable set is forbidden on a regression assessment and regression inputs are meaningless among comparables — and any shape violation is rejected with `ERR_ASSESSMENT_SHAPE`. The assessment is created `PROVISIONAL` with the computed `provisional_rent_cents`, and `determined_rent_cents` remains null until the assessment turns `FINAL`. Assessments are listable per option and filterable by `status`.

Only one provisional view of the market exists at a time. Submitting a fresh assessment while an earlier one is still `PROVISIONAL` moves the earlier row to `SUPERSEDED` and increments the option's `version` — which is exactly why submission carries the option's version token, evaluated after the state and shape checks: a stale read of the option yields `ERR_STALE_VERSION`.

Left unchallenged, an assessment finalizes by the calendar: once fifteen calendar days have passed since its creation with no dispute filed, a clock sweep moves it `PROVISIONAL` → `FINAL` and copies `provisional_rent_cents` into `determined_rent_cents`. When the parent option is sitting in `NOTICE_SENT` with its open notice already acknowledged, the exercise can now complete.

Disagreement becomes a formal dispute when the `AssetManager` files while the option is `NOTICE_SENT` or `IN_ARBITRATION` — the state check comes first, with other states rejected as `ERR_INVALID_STATE` — and while the clock date is on or before the assessment's creation date plus fifteen calendar days, with a later filing rejected as `ERR_DISPUTE_WINDOW_CLOSED`. The filing names both positions, `landlord_rent_cents` and `tenant_rent_cents`; it moves the assessment `PROVISIONAL` → `DISPUTED`; it creates an `ArbitrationCase` in `OPEN` whose `assessment_id` points at the disputed assessment and whose `submission_close_date` is server-stamped thirty calendar days after case creation, freezing submissions beyond that date; and it pushes the parent option `NOTICE_SENT` → `IN_ARBITRATION`. While the option sits in arbitration, notice-window lapse is suspended and its `PENDING` reminders remain pending but do not fire.

A case whose `submission_close_date` passes moves `OPEN` → `SUBMISSIONS_FROZEN`. From either `OPEN` or `SUBMISSIONS_FROZEN`, `LandlordCounsel` renders the decision by supplying a positive integer `panel_guidance_rent_cents`. This is baseball arbitration: the `award_rent_cents` is whichever of the two submissions — `landlord_rent_cents` or `tenant_rent_cents` — lies nearest the guidance rent, and an exact tie resolves to the lower of the two submissions. Deciding moves the case to `DECIDED` and cascades two hops. The assessment moves `DISPUTED` → `FINAL` with `determined_rent_cents` set to the award; when the award differs from the provisional rent, an `ARBITRATION_AWARD_ADJUSTMENT` ledger entry posts for the difference multiplied by the lease's `rentable_square_feet`, and when they are equal the entry is skipped. The option then returns `IN_ARBITRATION` → `NOTICE_SENT`, taking its determined rent from the now-final assessment, and its suspended reminders resume firing on the normal schedule.

### 3.7. Amendment Negotiation and Execution

Not every renewal rides an option; the amendment flow is the negotiated channel. An `AssetManager` opens a draft — bound to its lease by `lease_id` — with a `kind` of `RENEWAL_TERM`, `EXPANSION_TERM`, `CONTRACTION`, or `HOLDOVER_SETTLEMENT`, a proposed `new_expiration_date`, and a proposed `new_base_rent_cents_per_rsf_year` that must be greater than zero. Amendments form a self-referential chain: `supersedes_amendment_id` names the prior amendment on the same lease that this one replaces, it is null for the lease's first amendment, and it is validated for scope first — a value pointing at an amendment of a different lease is rejected with `ERR_FK_SCOPE_VIOLATION`. Temporal order follows: the proposed `new_expiration_date` must fall strictly after the lease's current `expiration_date`, else `ERR_TEMPORAL_ORDER`. A new amendment starts in `DRAFT`; amendments list per lease with `status` and `kind` filters.

Proposal moves a draft `DRAFT` → `PROPOSED` and stamps `negotiation_opened_at`. Three guards run in order: the lease must be `ACTIVE`, `EXPIRING`, or `HOLDOVER` (else `ERR_INVALID_STATE`); only one negotiation may be open per lease, so a sibling amendment sitting in `PROPOSED`, `COUNTERED`, or `AGREED` forces `ERR_NEGOTIATION_ALREADY_OPEN`; and the `expected_lease_version` token must match the lease's current `version` (else `ERR_STALE_VERSION`). Proposal also increments the lease's `version`.

The negotiation loop is cyclic. `LandlordCounsel` counters a `PROPOSED` amendment, moving it `PROPOSED` → `COUNTERED` with a revised `new_base_rent_cents_per_rsf_year`. The `AssetManager` re-proposes, moving it `COUNTERED` → `PROPOSED` and optionally revising `new_base_rent_cents_per_rsf_year` or `new_expiration_date`. Agreement is `LandlordCounsel`'s act from either `PROPOSED` or `COUNTERED`, moving the amendment to `AGREED`. Segregation of duties binds the two closing steps: the agreeing counsel's `X-User-ID` must differ from the `X-User-ID` of the asset manager who most recently moved the amendment to `PROPOSED`, and a breach is rejected with `ERR_SOD_VIOLATION` (HTTP 403).

Execution is the `AssetManager`'s act on an `AGREED` amendment, carrying `expected_lease_version` and optionally `enforce_ladder`. Its checks run in order: state admissibility; segregation of duties — the executor's `X-User-ID` must differ from the agreeing counsel's, else `ERR_SOD_VIOLATION`; the stale-version check; the ladder guard, which rejects with `ERR_LADDER_BREACH` when the flag is supplied and execution would push the portfolio into `LADDER_STRESSED`; and, for settlements, holdover presence. Execution moves the amendment to `EXECUTED`, stamps `executed_at`, records the amendment as the lease's `active_amendment_id`, applies `new_expiration_date` and `new_base_rent_cents_per_rsf_year` to the lease, and increments the lease's `version`. The kind selects the cascade. Executing a `RENEWAL_TERM` or `EXPANSION_TERM` amendment moves the lease to `RENEWED` per the lease lifecycle, applying the amendment's terms. Executing a `CONTRACTION` applies the new terms without changing the lease's lifecycle state. Executing a `HOLDOVER_SETTLEMENT` is valid only while the lease is actually in `HOLDOVER` — otherwise `ERR_NOT_IN_HOLDOVER` — and it returns the lease `HOLDOVER` → `ACTIVE`, clears `holdover_entered_at` to null, posts an `AMENDMENT_SETTLEMENT` ledger entry for the final accrued holdover delta, and resets `accrued_holdover_rent_cents` to zero. An amendment not yet executed — from `DRAFT`, `PROPOSED`, `COUNTERED`, or `AGREED` — may be abandoned by the `AssetManager`, moving it to `ABANDONED` and incrementing the lease's `version`.

Timing is part of the discipline. Negotiation must initiate early enough to close before expiration: the initiation deadline falls 270 days — nine months — before the lease's `expiration_date`. An amendment is `ON_TIME` when its `negotiation_opened_at` date falls on or before that deadline and `LATE` otherwise; it is `EXECUTION_COMPLIANT` only when its `executed_at` date falls strictly before the expiration date, so same-day execution is non-compliant. A lease with no amendment at all is flagged `NEGOTIATION_MISSING` once the clock passes the initiation deadline while the lease is `ACTIVE` or `EXPIRING`. A computed read reports these compliance flags per lease across the portfolio.

### 3.8. Lapse, Holdover, and the Cost of Missing Dates

The lapse sweep is the consequence engine. On any clock advance that carries the date past an option's `notice_window_close_date`, an option still in `AVAILABLE`, `WINDOW_OPEN`, or `NOTICE_SENT` — and not `EXERCISED`, `WITHDRAWN`, `IN_ARBITRATION`, or `SUPERSEDED` — moves to `LAPSED`, stamps `lapsed_at`, and cancels its `PENDING` reminders. When the option's `missed_option_penalty_cents` is positive, the lapse posts a `MISSED_OPTION_PENALTY` ledger entry for that amount with the clock date as its `effective_date` and the option as `source_option_id`; a zero-penalty lapse is silent, with only the status transition observable. Options parked in `IN_ARBITRATION` are explicitly exempt from the sweep until their arbitration resolves. Rather than letting an option lapse, an `AssetManager` may withdraw an unexercised option — from `AVAILABLE`, `WINDOW_OPEN`, or `NOTICE_SENT` — under the lease's version token, checked after state admissibility: the option moves to `WITHDRAWN`, its `PENDING` reminders are `CANCELED`, any of its notices still in `SENT` or `DELIVERED` become `VOID`, and the lease's `version` increments.

When the clock passes a lease's `expiration_date` with no renewal in place — no executed `RENEWAL_TERM` or `EXPANSION_TERM` amendment and no exercised `RENEWAL` option — and no timely vacatur on record, the lease rolls from `ACTIVE` or `EXPIRING` into `HOLDOVER`. Entry is backdated: `holdover_entered_at` is set to the day after `expiration_date` at 00:00:00 UTC regardless of when the sweep fires, marking the legal holdover start. The same transition lapses any of the lease's options still sitting in `AVAILABLE` or `WINDOW_OPEN`, posting each one's missed-option penalty when positive, and increments the lease's `version`.

Holdover rent accrues daily at punitive tiers, and the rounding order is pinned. The daily base is the lease's annual rent — `base_rent_cents_per_rsf_year` multiplied by `rentable_square_feet` — divided by 365 and rounded down to a whole cent. The first-tier daily charge is that daily base scaled by `holdover_tier1_pct` percent and rounded half up to a whole cent; the second-tier daily charge applies `holdover_tier2_pct` the same way. Days held are counted from `holdover_entered_at` exclusive — that is, starting the day after holdover entry — through the clock date inclusive. `accrued_holdover_rent_cents` is then the first-tier daily charge times the number of days held up to `holdover_tier1_days`, plus the second-tier daily charge times any days held beyond that count. The per-day tier amounts are rounded first, then multiplied by their day counts, then summed; computing unrounded tier subtotals and rounding only the grand total is a forbidden interpretation that can drift from the pinned result by as much as the number of days held minus one cents. The accrual recomputes on every clock advance while the lease remains in `HOLDOVER`, and the only exit from holdover runs through the settlement amendment described in §3.7.

## 4. Endpoint Definitions

Operations that create a new resource — a portfolio, contact, lease, option, exercise notice, assessment, arbitration case (via dispute), amendment draft, or clock event — answer `201 Created`. Operations that modify an existing resource's state, and all reads, answer `200 OK`. The designation "All roles" in the table covers `PlatformAdmin`, `AssetManager`, `Broker`, and `LandlordCounsel`; narrower entries restrict as listed. Request payloads, preconditions, and side effects are defined by the narratives of §2 and §3 rather than by this table.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Pin the logical clock and fire all scheduled sweeps | PlatformAdmin |
| POST | `/portfolios` | Create a portfolio | PlatformAdmin |
| GET | `/portfolios` | List portfolios (paginated) | All roles |
| GET | `/portfolios/{pid}` | Get a portfolio with derived posture fields | All roles |
| GET | `/portfolios/{pid}/ladder` | Expiration ladder exposure per calendar year and posture | All roles |
| GET | `/portfolios/{pid}/negotiations/compliance` | Per-lease negotiation timeline compliance | PlatformAdmin, AssetManager, LandlordCounsel |
| POST | `/portfolios/{pid}/contacts` | Register a contact | PlatformAdmin, AssetManager |
| GET | `/portfolios/{id}/contacts` | List contacts of a portfolio | All roles |
| GET | `/portfolios/{pid}/contacts/{cid}` | Get a contact | All roles |
| PATCH | `/portfolios/{pid}/contacts/{cid}` | Update a contact; deactivation cancels its pending reminders | PlatformAdmin, AssetManager |
| POST | `/portfolios/{pid}/leases` | Create a lease in DRAFT | PlatformAdmin, AssetManager |
| GET | `/portfolios/{id}/leases` | List leases of a portfolio | All roles |
| GET | `/portfolios/{pid}/leases/{lid}` | Get a lease | All roles |
| POST | `/portfolios/{pid}/leases/{lid}/activate` | Activate a DRAFT lease whose term has begun | AssetManager |
| POST | `/portfolios/{pid}/leases/{lid}/vacate` | Record tenant vacating at natural expiration | AssetManager |
| POST | `/portfolios/{pid}/leases/{lid}/options` | Register an option on a lease | AssetManager |
| GET | `/portfolios/{pid}/leases/{lid}/options` | List options of a lease | All roles |
| GET | `/portfolios/{pid}/leases/{lid}/options/{oid}` | Get an option | All roles |
| POST | `/portfolios/{pid}/leases/{lid}/options/{oid}/withdraw` | Withdraw an unexercised option | AssetManager |
| POST | `/portfolios/{pid}/leases/{lid}/options/{oid}/notices` | Deliver an exercise notice | AssetManager |
| GET | `/portfolios/{pid}/leases/{lid}/options/{oid}/notices` | List exercise notices of an option | All roles |
| GET | `/portfolios/{pid}/leases/{lid}/options/{oid}/notices/{nid}` | Get an exercise notice | All roles |
| POST | `/portfolios/{pid}/leases/{lid}/options/{oid}/notices/{nid}/deliver` | Broker confirms delivery | Broker |
| POST | `/portfolios/{pid}/leases/{lid}/options/{oid}/notices/{nid}/reject` | Broker marks delivery rejected | Broker |
| POST | `/portfolios/{pid}/leases/{lid}/options/{oid}/notices/{nid}/acknowledge` | Landlord counsel acknowledges receipt | LandlordCounsel |
| POST | `/portfolios/{pid}/leases/{lid}/options/{oid}/assessments` | Submit a market-rate assessment | AssetManager |
| GET | `/portfolios/{pid}/leases/{lid}/options/{oid}/assessments` | List assessments of an option | All roles |
| GET | `/portfolios/{pid}/leases/{lid}/options/{oid}/assessments/{mid}` | Get an assessment | All roles |
| POST | `/portfolios/{pid}/leases/{lid}/options/{oid}/assessments/{mid}/dispute` | Dispute a provisional assessment, opening arbitration | AssetManager |
| GET | `/portfolios/{pid}/leases/{lid}/options/{oid}/assessments/{mid}/arbitration` | Get the arbitration case of an assessment | All roles |
| POST | `/portfolios/{pid}/leases/{lid}/options/{oid}/assessments/{mid}/arbitration/decide` | Render the baseball-arbitration decision | LandlordCounsel |
| POST | `/portfolios/{pid}/leases/{lid}/amendments` | Open an amendment draft | AssetManager |
| GET | `/portfolios/{pid}/leases/{lid}/amendments` | List amendments of a lease | All roles |
| GET | `/portfolios/{pid}/leases/{lid}/amendments/{aid}` | Get an amendment | All roles |
| POST | `/portfolios/{pid}/leases/{lid}/amendments/{aid}/propose` | Move an amendment to PROPOSED | AssetManager |
| POST | `/portfolios/{pid}/leases/{lid}/amendments/{aid}/counter` | Landlord counters a proposal | LandlordCounsel |
| POST | `/portfolios/{pid}/leases/{lid}/amendments/{aid}/repropose` | Tenant revises terms after a counter | AssetManager |
| POST | `/portfolios/{pid}/leases/{lid}/amendments/{aid}/agree` | Landlord counsel agrees to the terms | LandlordCounsel |
| POST | `/portfolios/{pid}/leases/{lid}/amendments/{aid}/execute` | Execute an AGREED amendment | AssetManager |
| POST | `/portfolios/{pid}/leases/{lid}/amendments/{aid}/abandon` | Abandon an open amendment | AssetManager |
| GET | `/portfolios/{pid}/leases/{lid}/ledger` | List ledger entries of a lease | All roles |
| GET | `/portfolios/{pid}/leases/{lid}/options/{oid}/reminders` | List reminders of an option | All roles |
| GET | `/leases/{id}` | Flat read alias for a lease | All roles |
| GET | `/leases` | Flat filtered list of leases across portfolios | All roles |
| GET | `/options/{id}` | Flat read alias for an option | All roles |
| GET | `/assessments/{id}` | Flat read alias for a market-rate assessment | All roles |
| GET | `/contacts/{id}` | Flat read alias for a contact | All roles |
| GET | `/amendments/{id}` | Flat read alias for an amendment | All roles |
| GET | `/amendments` | Flat filtered list of amendments across leases | All roles |
| GET | `/leases/{id}/options` | Flat alias: options of a lease | All roles |
| GET | `/leases/{id}/amendments` | Flat alias: amendments of a lease | All roles |
| GET | `/leases/{id}/ledger` | Flat alias: ledger entries of a lease | All roles |
| GET | `/options/{id}/assessments` | Flat alias: assessments of an option | All roles |
| GET | `/options/{id}/notices` | Flat alias: exercise notices of an option | All roles |
| GET | `/options/{id}/reminders` | Flat alias: reminders of an option | All roles |
| GET | `/options/{id}/ledger` | Flat alias: ledger entries sourced from an option | All roles |
| GET | `/assessments/{id}/arbitration` | Flat alias: arbitration case of an assessment | All roles |
| GET | `/assessments/{id}/ledger` | Flat alias: ledger entries sourced from an assessment | All roles |
| GET | `/contacts/{id}/reminders` | Flat alias: reminders addressed to a contact | All roles |

## 5. Error Code Catalogue

Trigger conditions for each error live with the workflows they guard in §2 and §3; this catalogue is only the index of identifiers to HTTP status codes.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN` | 403 Forbidden |
| `ERR_SOD_VIOLATION` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_NEGOTIATION_ALREADY_OPEN` | 409 Conflict |
| `ERR_NOTICE_ALREADY_OPEN` | 409 Conflict |
| `ERR_NOT_IN_HOLDOVER` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_VALIDATION` | 400 Bad Request |
| `ERR_NOTICE_WINDOW_CLOSED` | 422 Unprocessable Entity |
| `ERR_DISPUTE_WINDOW_CLOSED` | 422 Unprocessable Entity |
| `ERR_TEMPORAL_ORDER` | 422 Unprocessable Entity |
| `ERR_RATE_TERMS_INCOHERENT` | 422 Unprocessable Entity |
| `ERR_ASSESSMENT_SHAPE` | 422 Unprocessable Entity |
| `ERR_LADDER_BREACH` | 422 Unprocessable Entity |
| `ERR_FK_SCOPE_VIOLATION` | 422 Unprocessable Entity |
| `ERR_ACK_AFTER_WINDOW` | 422 Unprocessable Entity |
