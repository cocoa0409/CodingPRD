# Eviction Diversion Portal API — Product Requirements Document

## 1. Introduction

Housing courts sit at the intersection of two opposing pressures: the landlord's statutory right to recover possession of a rented dwelling, and a public-policy commitment to keep tenants housed wherever an eviction can be diverted through mediation, a repayment agreement, or emergency rental assistance. The Eviction Diversion Portal is the system of record that coordinates that entire lifecycle — from the moment a landlord files a complaint, through service of process, the tenant's answer, referral to legal-aid and rental-assistance programs, mediation and payment-plan negotiation, the hearing calendar, judgment and stay, sheriff lockout scheduling, and finally the sealing or expungement of the closed record.

This document specifies the portal's REST API. The domain is deliberately intricate: a single case is a long-lived aggregate whose status advances through a branching state machine, while a second, independent **outcome** dimension tracks the socially meaningful result (was the tenancy preserved, dismissed, or enforced?). Money moves through the case along two separate channels — tenant installment payments and program-disbursed rental assistance — and every such movement recomputes the outstanding arrears, which in turn can automatically satisfy a diversion and cascade cancellations across the hearing calendar and any open negotiation. Enforcement is gated by segregation-of-duties rules (a judge may not rule on a case they personally mediated), by temporal stays, and by an officer's scheduling buffer.

The requirements below define the resource model, the global response and concurrency contracts, the business workflows with their precise thresholds and cascades, the full endpoint surface, and the error catalogue. All time-dependent behaviour is driven by a server-controlled **logical clock**, never by wall-clock time, so that deadlines, waiting periods, and scheduling windows are deterministic and testable.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request to an authenticated endpoint must carry two headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, naming that principal's role. The recognised roles are exactly `Clerk`, `Landlord`, `Tenant`, `Mediator`, `Judge`, `ProgramAdmin`, and `Sheriff`. If either header is missing, or `X-User-Role` names a value that is not one of these seven roles, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). If the headers are well-formed but the role is not permitted to perform the requested operation — or an ownership-scoped role acts on a resource it does not own — the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

The bootstrap configuration endpoints — registering a court, a landlord, a tenant, or an officer, and setting the logical clock — are the only operations exempt from authentication when no auth context is supplied; every other endpoint requires valid headers.

Two of the seven roles are **entity-backed**, meaning their `X-User-ID` is the identifier of a persisted party record. When `X-User-Role` is `Landlord`, `X-User-ID` is the `id` of the acting `Landlord`; ownership checks on any case-linked resource compare the case's `landlord_id` to `X-User-ID`, so a landlord may only act on cases they filed and their descendant artefacts. When `X-User-Role` is `Tenant`, `X-User-ID` is the `id` of the acting `Tenant`; ownership checks compare the case's `tenant_id` to `X-User-ID`, so a tenant may only answer, negotiate, pay, and seal on their own cases. The remaining five roles are opaque operator identities. When `X-User-Role` is `Clerk`, `X-User-ID` is an opaque court-operator identifier not tied to any persisted entity. When `X-User-Role` is `Mediator`, `X-User-ID` is an opaque identifier; the server records it as the `mediator_user_id` of any session that mediator conducts and later reads it back when enforcing segregation of duties, but it is not compared to any entity's `id`. When `X-User-Role` is `Judge`, `X-User-ID` is an opaque identifier that the server records as `entered_by_user_id` on any judgment the judge enters and as `decided_by_user_id` on any sealing request the judge decides; it is not an entity key. When `X-User-Role` is `ProgramAdmin`, `X-User-ID` is an opaque program-administrator identifier not tied to any entity. When `X-User-Role` is `Sheriff`, `X-User-ID` is an opaque enforcement-operator identifier; the officer actually assigned to a lockout is named separately by `officer_id` and is not derived from the header.

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

All list endpoints accept two optional query parameters, `limit` and `offset`. The `limit` defaults to 10 when omitted, must be at least 1, and may not exceed 100; the `offset` defaults to 0 and must be at least 0. List results are ordered by `created_at` ascending — that is, oldest record first — and any secondary filters named on a list endpoint are applied before pagination. The `meta` block of a list response reports the effective `limit` and `offset`, the `total_count` of records matching the filter before the page window is applied, and `has_more`, a boolean that is true when records remain beyond the current page.

### 2.4. Common Resource Properties, Identifiers, and Versioning

Every resource carries a server-minted `id` — a UUID with no type prefix — assigned at creation and never reused. Every resource also carries `created_at`, an ISO 8601 UTC timestamp with three fractional digits recording the logical-clock instant of creation.

Most resources additionally carry `updated_at` and `version`. `updated_at` is an ISO 8601 UTC timestamp refreshed to the current logical-clock instant on every mutation; `version` is an integer that begins at 1 on creation and increments by exactly 1 on every mutation of that resource. These fields are present on `Court`, `Case`, `Referral`, `MediationSession`, `PaymentPlan`, `Installment`, `Hearing`, `Judgment`, `LockoutOrder`, and `SealingRequest`. Four resources are lightweight records that carry only `id` and `created_at` — they have neither `updated_at` nor `version`: the `Landlord`, the `Tenant`, the `Officer`, and the `Answer`. An `Answer` is written once and never mutated thereafter, so it needs no version.

When an operation mutates several resources at once (the cascades described throughout §3), each affected versioned resource independently bumps its own `version` and refreshes its own `updated_at`.

Every workflow resource additionally carries a `status` field holding its current lifecycle state (the exact state strings are enumerated per entity in §3), and the case alone carries a second, independent `outcome` field tracking the socially meaningful disposition described in §3.7.

### 2.5. The Logical Clock and Temporal Semantics

The portal never reads wall-clock time. A single server-wide **logical clock** governs every deadline, waiting period, due date, stay expiry, and scheduling window. At startup the clock reads `2026-05-01T00:00:00Z`, and it only ever advances when an operator explicitly sets it; it never falls back to real time. Setting the clock supplies a target instant, `to_iso8601`, and all subsequent time-dependent evaluations read the new value.

Because all temporal comparisons resolve against this clock, computed timestamps such as `served_at`, `closed_at`, `paid_at`, `executed_at`, and `answer_due_at` are all captured as the logical-clock instant in effect at the moment of the triggering event, and are rendered in the same ISO 8601 UTC form as `created_at`.

### 2.6. Optimistic Concurrency Control

Opening a payment-plan negotiation is guarded by optimistic concurrency on the parent case. A create-payment-plan request must carry `expected_case_version`, a non-optional field holding the `version` of the target `Case` that the client last observed. The server compares it to the case's current `version`; if they do not match — because some other writer has advanced the case since the client last read it — the create is rejected with `ERR_STALE_VERSION` (HTTP 412). A newly opened plan legitimately supersedes the case's prior negotiation posture (its arrears baseline and plan slot), so a create carrying a stale `expected_case_version` must be refused on the stale-version check rather than silently opening a second negotiation over an out-of-date arrears figure. On a successful create, the case's `version` is incremented by 1. No other endpoint accepts or requires a version field.

### 2.7. Monetary Precision, Rounding, and Cents Conventions

All monetary quantities are integer cents: `claimed_arrears_cents`, `net_arrears_cents`, `rent_withheld_cents`, `household_income_cents`, `requested_amount_cents`, `disbursed_amount_cents`, `total_cents`, `amount_cents`, and `money_amount_cents`. Arrears figures are floored at 0 — they never go negative. The installment schedule uses a floor-then-remainder allocation described in §3.5; every other monetary calculation is an exact integer sum or difference with no rounding. The rental-assistance award is an exact minimum of three integer inputs, again with no rounding.

### 2.8. Validation Ordering and Error Precedence

When more than one thing is wrong with a request, checks are applied in a fixed order and the first failing check determines the error returned. The order is: (1) authentication — `X-User-ID` and `X-User-Role` present and the role recognised, else `ERR_UNAUTHENTICATED`; (2) authorization — the role is permitted for this operation and, for entity-backed roles, owns the target resource, else `ERR_UNAUTHORIZED`; (3) body well-formedness — required fields present, enum values in range, numeric fields at least their declared minimums, and any `scheduled_start` strictly before its `scheduled_end`, else `ERR_VALIDATION`; (4) existence — every path identifier and every foreign key in the body resolves, left to right, to a live resource, else `ERR_NOT_FOUND`; (5) optimistic concurrency — `expected_case_version` matches on plan create, else `ERR_STALE_VERSION`; (6) state legality — the target resource is in a state from which the requested transition is legal, else `ERR_INVALID_STATE`; (7) referential state — a referenced sibling entity is in the state this action requires, else the action-specific referential error; (8) segregation-of-duties and sealing eligibility, else `ERR_SOD_VIOLATION` or `ERR_SEALING_INELIGIBLE`; (9) temporal gates — answer windows, not-due checks, active stays, waiting periods, else the action-specific temporal error; (10) resource capacity and overlap — hearing conflicts, calendar capacity, officer buffer, else the action-specific capacity error; (11) fiscal sufficiency — plan total covers arrears, program budget not exhausted, else the action-specific fiscal error. Lower-numbered categories always take precedence over higher-numbered ones.

### 2.9. Cascading State Effects and Calendar/Ledger Invariants

Many transitions in this domain do more than change one resource's status; they propagate. The precise cascades — a satisfied diversion cancelling scheduled hearings and withdrawing open plans, a vacated judgment dismissing its case and cancelling its lockouts, a paid final installment completing a plan and satisfying the case — are specified with their triggering workflows in §3. Two invariants hold globally regardless of which path reached them. First, a court's `hearings_scheduled_count` always equals the number of `Hearing` rows on that court whose status is `SCHEDULED`: it starts at 0 when the court is registered, increases by 1 whenever a hearing is scheduled (including the successor created by a continuance), and decreases by 1 whenever a scheduled hearing leaves `SCHEDULED` by being held, cancelled, or continued. Second, a case's outstanding arrears (`net_arrears_cents`) always equals the claimed amount at filing reduced by paid installments and disbursed rental assistance, floored at 0, as detailed in §3.

### 2.10. Nested Resource Retrieval and Ownership Scoping

The portal exposes a flat topology: every resource lives under its own top-level collection and is addressed by its own identifier, with relationships expressed through foreign-key fields carried in request bodies rather than through nested URL paths. When a request names both a path identifier and body foreign keys, existence is validated left to right — the path resource first, then each referenced foreign key — and the first unresolved reference yields `ERR_NOT_FOUND`. List endpoints support filtering by the foreign keys and status values noted with each collection in §4; ownership-scoped roles see only records belonging to their own cases. A sealed case is withheld from the default case listing (see §3.9) but remains directly fetchable by its identifier.

## 3. Business Logic & Workflows

### 3.1. Registering Courts, Parties, and Officers

Before any case can be filed, a court clerk seeds the reference data. Registering a housing court captures its `name`, its `jurisdiction_code` (a state or county identifier), and its `hearing_daily_capacity` — the maximum number of hearings the court may hold as `SCHEDULED` on any single calendar date, which must be at least 1. A freshly registered court begins with a `hearings_scheduled_count` of 0; this live counter is maintained automatically thereafter and is never supplied by a client.

The two adversarial parties are registered separately. A landlord (the plaintiff) record captures a `name` and a contact `email`. A tenant (the respondent) record captures a `name`, a contact `email`, and two figures that later drive the rental-assistance income cap: `household_income_cents`, the monthly household income in cents, which may not be negative; and `household_size`, the number of household members, which must be at least 1. Enforcement personnel are registered as officer records capturing a `name`, a `badge_number`, and the `agency` (sheriff or marshal) the officer serves. All four registration operations are performed by a `Clerk`; the `Landlord`, `Tenant`, and `Officer` records are lightweight and carry neither a version nor an update timestamp.

### 3.2. Filing, Service, and the Answer Window

A case is opened by the plaintiff or on their behalf, and enters the world in status `FILED` with its outcome dimension set to `PENDING` and `sealed` false. Filing captures the `court_id` where the matter is docketed, the `landlord_id` of the filing party, the `tenant_id` of the respondent, and the `filing_type`, which is one of `NONPAYMENT`, `HOLDOVER`, or `NUISANCE`. A money claim, `claimed_arrears_cents`, is optional and defaults to 0 (holdover and nuisance filings claim no arrears); when supplied it may not be negative. At filing the case's outstanding balance, `net_arrears_cents`, is seeded to the claimed amount — the provisional variant of the arrears calculation, which simply equals `claimed_arrears_cents` before any money has moved.

The deadline by which the tenant must respond, `answer_due_at`, is fixed at creation as the case's `created_at` instant plus a two-week answer window (fourteen days). This deadline is frozen at filing and does not shift when the case is later served.

A clerk serves process by advancing the case from `FILED` to `SERVED`, which stamps `served_at` with the current logical-clock instant. From `SERVED`, the case can move in one of two directions. If the tenant responds, they file an answer: an answer captures its `case_id`, a list of asserted `defenses` drawn from `WARRANTY_OF_HABITABILITY`, `IMPROPER_SERVICE`, `RENT_PAID`, `RETALIATION`, and `DISCRIMINATION`, and an optional `rent_withheld_cents` (the amount claimed to have been lawfully withheld, defaulting to 0 and never negative). Creating the answer is the system event that moves the case from `SERVED` to `ANSWERED`. The answer's `is_late` flag is computed as true exactly when the answer's `created_at` falls strictly after the parent case's `answer_due_at`; an on-time answer filed at or before the deadline is not late. An answer may only be filed against a served case; once the case has moved to `DEFAULTED`, an attempt to answer is refused with `ERR_ANSWER_WINDOW_CLOSED`.

Alternatively, if the tenant never responds, the clerk may take a default, advancing the case to `DEFAULTED`. Taking a default is state-legal from either `SERVED` or `ANSWERED` (any other source status yields `ERR_INVALID_STATE`); it is then gated twice, in this order: the current logical-clock instant must be at or after `answer_due_at` (attempting it while the window is still open yields `ERR_ANSWER_WINDOW_OPEN`), and no answer may already exist for the case (otherwise `ERR_ALREADY_ANSWERED`). Because filing an answer is exactly what moves a case to `ANSWERED`, a default attempted against an `ANSWERED` case whose window has closed always fails the second gate with `ERR_ALREADY_ANSWERED`, so a default only ever succeeds from `SERVED`. From `ANSWERED`, a clerk may also move the case directly into `IN_LITIGATION` when no diversion is pursued.

### 3.3. Diversion Referrals and Rental Assistance

Once a case is answered, the tenant (or a clerk acting for them) may seek help from aid programs by submitting a referral. A referral records its `case_id`, a `referral_type` of either `LEGAL_AID` or `RENTAL_ASSISTANCE`, and the `provider_name` of the organisation or program. A new referral is born `SUBMITTED`. The first referral or the first mediation session created for an answered case is the system event that moves the case from `ANSWERED` into `IN_DIVERSION`, signalling that a diversion track is underway while the outcome dimension stays `PENDING`.

A program administrator decides each referral. Approval moves it from `SUBMITTED` to `APPROVED`, but only while the parent case is neither sealed nor in a terminal status. For a `LEGAL_AID` referral, approval leaves `requested_amount_cents` at 0. For a `RENTAL_ASSISTANCE` referral, approval computes and stores `requested_amount_cents` as the provisional award: the smallest of three independent figures — the case's current outstanding arrears, the household income cap, and the program's remaining budget. The **income cap** is a base of three thousand dollars plus one thousand dollars for each household member beyond the first; that is, `INCOME_CAP_BASE_CENTS` of 300000 plus `household_size` minus one, multiplied by `INCOME_CAP_PER_MEMBER_CENTS` of 100000. The **remaining budget** is the program's total endowment of fifty thousand dollars — `ASSISTANCE_PROGRAM_BUDGET_CENTS` of 5000000 — reduced by the sum of `disbursed_amount_cents` across every referral program-wide that has reached `DISBURSED`. A referral may instead be denied, moving it from `SUBMITTED` to `DENIED`.

Disbursement moves an approved referral from `APPROVED` to `DISBURSED` and is the point at which money actually changes hands. Two guards apply: the referral must be of type `RENTAL_ASSISTANCE` (attempting to disburse a `LEGAL_AID` referral is refused with `ERR_NOT_DISBURSABLE`), and the program's remaining budget must be at least one cent (a fully exhausted budget yields `ERR_ASSISTANCE_BUDGET_EXCEEDED`). At disbursement the final award, `disbursed_amount_cents`, is recomputed as the smallest of three figures — the case's current outstanding arrears at this instant, the `requested_amount_cents` fixed at approval, and the program's currently remaining budget — because the arrears may have fallen through interim payments between approval and disbursement, so the disbursed amount can be strictly less than the requested amount. Disbursement then reduces the case's `net_arrears_cents` by `disbursed_amount_cents` (the first cascade hop). If that reduction brings the case's outstanding arrears to exactly 0 while the case is `IN_DIVERSION`, the case is automatically satisfied — it advances to `DIVERSION_SATISFIED`, which itself triggers the closing cascade described in §3.5 and §3.7.

### 3.4. Mediation Sessions

Mediation runs in parallel with the referral track. A session is scheduled with its `case_id`, the `mediator_user_id` of the neutral conducting it (recorded from the acting mediator's identity for later segregation-of-duties enforcement), and a `scheduled_at` instant; free-text `outcome_notes` default to an empty string and are typically filled in when the session is held. A new session is born `SCHEDULED`, and like a referral, the first mediation session created for an answered case moves that case from `ANSWERED` to `IN_DIVERSION`.

The mediator conducts the session by advancing it from `SCHEDULED` to `HELD`, which is permitted only once the current logical-clock instant has reached or passed the session's `scheduled_at`. A held session concludes one of two ways. If the parties reach terms, it advances from `HELD` to `AGREEMENT`; should the case happen to be `IN_LITIGATION` at that moment, reaching agreement pulls it back to `IN_DIVERSION`. If the parties cannot agree, the session advances from `HELD` to `IMPASSE`. An impassed session is not the end of the road: it may be rescheduled, moving from `IMPASSE` back to `SCHEDULED` with a fresh `scheduled_at`, and this loop may repeat as many times as needed.

### 3.5. Payment-Plan Negotiation and Installment Repayment

A repayment agreement is the most common way a nonpayment case is diverted, and it is negotiated as a back-and-forth between the two parties. Either party opens a plan, recording the `case_id`, `proposed_by` (`LANDLORD` or `TENANT`, the party opening the negotiation), a `total_cents` to be repaid (at least 1), an `installment_count` of equal payments (at least 1), and a `first_due_date` for the opening installment. Opening a plan is guarded by optimistic concurrency: the request must carry `expected_case_version` matching the case's current `version`, and on success the case's `version` is incremented by 1 (see §2.6). The plan is born `PROPOSED`, and `current_proposer` is set to the counterparty of `proposed_by` — the party whose turn it now is to respond.

Responses drive the negotiation. Each response carries a `decision` of `ACCEPT`, `COUNTER`, or `REJECT`, and in every case the acting party must be the one whose turn it is — the counterparty named by `current_proposer`. A response from the wrong party is refused with `ERR_WRONG_PARTY_TURN`. A counter-offer supplies `new_total_cents` and `new_installment_count`; it overwrites the plan's `total_cents` and `installment_count` with the countered terms and flips `current_proposer` to the other party. Countering moves a `PROPOSED` plan to `COUNTERED`, and a subsequent counter moves it from `COUNTERED` back to `PROPOSED`, so the offer can bounce between the parties indefinitely. Either side may reject, moving the plan from `PROPOSED` or `COUNTERED` to `REJECTED` and ending the negotiation.

Acceptance settles the plan. It moves the plan from `PROPOSED` or `COUNTERED` to `ACCEPTED`, but only if the plan's `total_cents` is at least the case's current final outstanding arrears; a plan that would leave arrears uncovered is refused with `ERR_PLAN_INSUFFICIENT`. On acceptance, `current_proposer` is cleared to null, the installment schedule is generated (below), and — if the case is `ANSWERED` or `IN_LITIGATION` — the case is pulled into `IN_DIVERSION`.

The **installment schedule** divides the accepted `total_cents` across `installment_count` equal payments where the order of operations is fixed: first compute the per-installment floor as the total divided by the count, dropping any fraction; the leftover remainder is the total minus that floor multiplied by the count. Every installment is assigned the floor amount, except the final installment, which additionally absorbs the entire remainder — so the sum of all installment amounts equals the plan total exactly. Each generated installment records its parent `payment_plan_id`, a 1-based `sequence` giving its ordinal position, its `amount_cents`, and a `due_date` computed as the plan's `first_due_date` plus thirty days for each position past the first (the first installment falls on `first_due_date`, the second thirty days later, and so on, at a fixed thirty-day cadence). Each installment starts `DUE`, with `paid_at` null.

A tenant pays an installment by moving it from `DUE` to `PAID`, which is allowed only while the parent plan is `ACCEPTED` (otherwise `ERR_INVALID_STATE`). Paying stamps `paid_at` with the current instant and reduces the case's `net_arrears_cents` by that installment's `amount_cents`. Paying the last outstanding installment — the moment every installment of the plan is `PAID` — bubbles the plan up from `ACCEPTED` to `COMPLETED`, which in turn satisfies the case (`DIVERSION_SATISFIED`). A clerk marks an installment `MISSED`, moving it from `DUE` to `MISSED`, only after its `due_date` has strictly passed (attempting it at or before the due date yields `ERR_INSTALLMENT_NOT_DUE`) and while the parent plan is `ACCEPTED`; a single missed installment bubbles the plan up to `DEFAULTED`. When a plan defaults and its case was `IN_DIVERSION`, the case is relitigated — pushed from `IN_DIVERSION` to `IN_LITIGATION`.

The case's **final outstanding arrears** — the figure acceptance is checked against, the figure disbursement and payment reduce, and the figure a possession judgment is built on — is always the claimed amount at filing minus the sum of `amount_cents` across the case's paid installments (on its accepted, completed, or defaulted plan) minus the sum of `disbursed_amount_cents` across the case's disbursed rental-assistance referrals, floored at 0 so it never goes below zero.

### 3.6. The Hearing Calendar and Continuances

Hearings occupy a court's calendar as half-open time intervals. Scheduling a hearing records its `case_id`, the `court_id` whose calendar it occupies, a `hearing_type` of `INITIAL`, `TRIAL`, or `ENFORCEMENT`, and the interval bounds `scheduled_start` and `scheduled_end`, where the end must be strictly after the start. A new hearing is born `SCHEDULED`, its `continuance_count` is 0, its `continued_from_id` is null, and the court's `hearings_scheduled_count` is incremented by 1.

Two calendar constraints are enforced against the target court before a hearing may occupy a slot. First, the requested interval must not overlap any other `SCHEDULED` hearing on the same court: two intervals conflict when the new start falls before the other's end and the other's start falls before the new end. Because the intervals are half-open, adjacency is allowed — a hearing whose start equals another's end does not overlap. An overlap is refused with `ERR_HEARING_CONFLICT`. Second, the number of `SCHEDULED` hearings already on that court that fall on the same calendar date (the UTC date of `scheduled_start`) must be below the court's `hearing_daily_capacity`; if the date is already at capacity, the request is refused with `ERR_CALENDAR_FULL`.

A judge holds a hearing by moving it from `SCHEDULED` to `HELD`, which requires two things: the parent case must be `IN_LITIGATION` (otherwise `ERR_CASE_NOT_IN_LITIGATION`), and the current logical-clock instant must be at or after `scheduled_start`. Holding a hearing releases its slot, decrementing the court's `hearings_scheduled_count` by 1. A clerk may cancel a scheduled hearing, moving it from `SCHEDULED` to `CANCELLED` and likewise releasing the slot.

A continuance reschedules a hearing to a new interval. A clerk continues a hearing by supplying `new_start` and `new_end`; the new interval must be well-formed (`new_start` strictly before `new_end`, otherwise `ERR_INVALID_INTERVAL`) and must itself clear both calendar checks against the court — no half-open overlap with another scheduled hearing (`ERR_HEARING_CONFLICT`) and room within the daily capacity for the new date (`ERR_CALENDAR_FULL`). The original hearing moves from `SCHEDULED` to `CONTINUED` and releases its slot. In the same operation a successor hearing is created `SCHEDULED` on the new interval, with its `continued_from_id` pointing back to the original, its `continuance_count` set to one more than the predecessor's, and the court's `hearings_scheduled_count` incremented by 1 for the successor.

### 3.7. Judgments, Stays, and the Outcome Dimension

A judge disposes of a litigated case by entering a judgment. Entering a judgment records the `case_id` and a `judgment_type` of `POSSESSION`, `DISMISSAL`, or `DIVERSION`, which forks the downstream effects. Every judgment is stamped with `entered_by_user_id` — the entering judge's identity — and this is where segregation of duties bites: the judge entering a judgment must not be the same person recorded as the `mediator_user_id` on any mediation session of the case that reached `HELD` or `AGREEMENT`. A judge who mediated the case may not then rule on it, and the attempt is refused with `ERR_SOD_VIOLATION`.

The fork determines both the money and the case's fate. A `POSSESSION` judgment computes `money_amount_cents` as the case's final outstanding arrears plus a filing fee of forty-five dollars (`JUDGMENT_FILING_FEE_CENTS` of 4500) and advances the case (from `IN_LITIGATION` or `DEFAULTED`) to `JUDGMENT_ENTERED`, setting the outcome dimension to `JUDGMENT_FOR_LANDLORD`. A `DISMISSAL` judgment carries `money_amount_cents` of 0 and moves the case from `IN_LITIGATION` to `DISMISSED`, stamping `closed_at` and setting the outcome to `DISMISSED`. A `DIVERSION` judgment likewise carries no money and moves the case to `IN_DIVERSION`. A judgment is born in status `ENTERED`.

The **outcome** dimension evolves independently of the case status and always begins at `PENDING`; over a case's life it may become `DIVERTED` (when a diversion is satisfied), `JUDGMENT_FOR_LANDLORD` (on a possession judgment), `DISMISSED` (on a dismissal or a vacatur), or `ENFORCED` (once a lockout executes).

A judge may act further on an entered judgment. Staying it moves it from `ENTERED` to `STAYED` and sets `stay_until`, the instant until which enforcement is blocked; the stay instant must be strictly in the future relative to the current clock (otherwise `ERR_INVALID_INTERVAL`). Lifting a stay moves the judgment from `STAYED` back to `ENTERED` and clears `stay_until` to null. Vacating a judgment — from either `ENTERED` or `STAYED` — dismisses the underlying case: a case in `JUDGMENT_ENTERED` or `ENFORCEMENT` moves to `DISMISSED`, its `closed_at` is stamped and its outcome set to `DISMISSED` (the first cascade hop), and any `REQUESTED` or `SCHEDULED` lockout order on the case is cancelled and its officer freed (the second hop). Finally, a possession judgment that has been paid off may be marked satisfied, moving from `ENTERED` to `SATISFIED`; this is permitted only when the `judgment_type` is `POSSESSION`.

### 3.8. Sheriff Lockout Scheduling and Enforcement

When a possession judgment stands, the landlord (or a clerk) requests a sheriff lockout, recording the `case_id` and the `judgment_id` of the authorising judgment. The order is born `REQUESTED` with its `officer_id`, `scheduled_at`, and `executed_at` all null.

A sheriff schedules the lockout by moving it from `REQUESTED` to `SCHEDULED`, supplying the `officer_id` to assign and the `scheduled_at` instant. Three guards apply in turn. The referenced judgment must be of type `POSSESSION` and in status `ENTERED` or `STAYED`; a vacated, satisfied, or non-possession judgment yields `ERR_NO_POSSESSION_JUDGMENT`. If the judgment is `STAYED`, the `scheduled_at` must be at or after the judgment's `stay_until`; scheduling inside an active stay yields `ERR_LOCKOUT_STAY_ACTIVE`. And the assigned officer must be free: they may have no other `SCHEDULED` lockout whose `scheduled_at` is within a forty-eight-hour buffer of this one. Two lockouts for the same officer must be at least forty-eight hours apart (`LOCKOUT_BUFFER_HOURS` of 48) — exactly forty-eight hours apart is allowed, and a gap strictly less than that is refused with `ERR_OFFICER_UNAVAILABLE`. On success the `officer_id` and `scheduled_at` are recorded and the case advances from `JUDGMENT_ENTERED` to `ENFORCEMENT`.

The sheriff executes the lockout by moving it from `SCHEDULED` to `EXECUTED`. Execution requires that the current logical-clock instant be at or after `scheduled_at` (otherwise `ERR_LOCKOUT_NOT_DUE`) and that the referenced judgment currently be in status `ENTERED` — a judgment that has since been vacated or re-stayed blocks execution with `ERR_NO_POSSESSION_JUDGMENT`. Execution stamps `executed_at` and closes the case, advancing it from `ENFORCEMENT` to `CLOSED_ENFORCED`, stamping the case's `closed_at`, and setting the outcome to `ENFORCED`. A lockout may also be cancelled from either `REQUESTED` or `SCHEDULED`; cancelling a scheduled order frees the officer's buffer window.

### 3.9. Sealing and Expungement of Closed Records

Once a case has closed, the tenant may petition to seal or expunge its record. A sealing request records the `case_id` and the statutory `basis` asserted — one of `DISMISSAL`, `DIVERSION`, or `TIME_ELAPSED`. Eligibility is checked when the request is created: the case must be in one of the terminal statuses `DISMISSED`, `DIVERSION_SATISFIED`, or `CLOSED_ENFORCED`, its `closed_at` must be set, and the current logical-clock instant must be at or after `closed_at` plus a ninety-day waiting period (`SEALING_WAIT_DAYS` of 90). Reaching exactly the ninety-day mark satisfies the wait; a request that fails any part of this test is refused with `ERR_SEALING_INELIGIBLE`. A new request is born `REQUESTED`.

A judge decides the request, and the deciding judge's identity is recorded as `decided_by_user_id` either way. Granting moves the request from `REQUESTED` to `GRANTED`, sets the parent case's `sealed` flag to true, and thereby removes the case from the default case listing; a sealed case is still directly retrievable by its identifier, and callers may opt back into seeing sealed cases in a listing by passing the `include_sealed` filter. Denying moves the request from `REQUESTED` to `DENIED`.

## 4. Endpoint Definitions

The table below summarises the API surface. Creating a new resource returns HTTP 201; fetching, listing, and every state-transition or response operation returns HTTP 200. Each state-transition endpoint (`/transition`) accepts a `to_status` field naming the target status, alongside any additional fields noted for that workflow in §3; the `/respond` endpoint takes a `decision`. Request bodies, response payloads, and side effects are not repeated here — reconstruct them from the workflow narratives in §3.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| POST | `/_clock/set_current_utc` | Set the server logical clock | Clerk |
| POST | `/courts` | Register a housing court | Clerk |
| GET | `/courts/{courtId}` | Fetch a court | Clerk, Landlord, Tenant, Mediator, Judge, ProgramAdmin, Sheriff |
| POST | `/landlords` | Register a landlord (plaintiff) party | Clerk |
| GET | `/landlords/{landlordId}` | Fetch a landlord | Clerk, Landlord, Tenant, Mediator, Judge, ProgramAdmin, Sheriff |
| POST | `/tenants` | Register a tenant (respondent) party | Clerk |
| GET | `/tenants/{tenantId}` | Fetch a tenant | Clerk, Landlord, Tenant, Mediator, Judge, ProgramAdmin, Sheriff |
| POST | `/officers` | Register an enforcement officer | Clerk |
| GET | `/officers/{officerId}` | Fetch an officer | Clerk, Landlord, Tenant, Mediator, Judge, ProgramAdmin, Sheriff |
| POST | `/cases` | File a new eviction case | Landlord, Clerk |
| GET | `/cases/{caseId}` | Fetch a case (returns sealed cases when fetched by id) | Clerk, Landlord, Tenant, Mediator, Judge, ProgramAdmin, Sheriff |
| GET | `/cases` | List cases; sealed cases excluded unless `include_sealed` is true | Clerk, Landlord, Tenant, Mediator, Judge, ProgramAdmin, Sheriff |
| POST | `/cases/{caseId}/transition` | Clerk-driven case status transition | Clerk |
| POST | `/answers` | Tenant files an answer to a served case | Tenant |
| GET | `/answers/{answerId}` | Fetch an answer | Clerk, Landlord, Tenant, Mediator, Judge |
| GET | `/answers` | List answers (filter by case) | Clerk, Landlord, Tenant, Mediator, Judge |
| POST | `/referrals` | Submit a legal-aid or rental-assistance referral | Tenant, Clerk |
| GET | `/referrals/{referralId}` | Fetch a referral | Clerk, Landlord, Tenant, ProgramAdmin, Judge |
| GET | `/referrals` | List referrals (filter by case/type/status) | Clerk, Landlord, Tenant, ProgramAdmin, Judge |
| POST | `/referrals/{referralId}/transition` | Program admin decides/disburses a referral | ProgramAdmin |
| POST | `/mediation-sessions` | Schedule a mediation session | Clerk, Mediator |
| GET | `/mediation-sessions/{sessionId}` | Fetch a mediation session | Clerk, Landlord, Tenant, Mediator, Judge |
| GET | `/mediation-sessions` | List mediation sessions (filter by case/status) | Clerk, Landlord, Tenant, Mediator, Judge |
| POST | `/mediation-sessions/{sessionId}/transition` | Mediator transitions a session | Mediator |
| POST | `/payment-plans` | Open a repayment-plan negotiation (OCC-guarded) | Landlord, Tenant |
| GET | `/payment-plans/{planId}` | Fetch a payment plan | Clerk, Landlord, Tenant, Mediator, Judge |
| GET | `/payment-plans` | List payment plans (filter by case/status) | Clerk, Landlord, Tenant, Mediator, Judge |
| POST | `/payment-plans/{planId}/respond` | Counterparty responds to a plan | Landlord, Tenant |
| GET | `/installments/{installmentId}` | Fetch an installment | Clerk, Landlord, Tenant, Judge |
| GET | `/installments` | List installments (filter by plan/status) | Clerk, Landlord, Tenant, Judge |
| POST | `/installments/{installmentId}/transition` | Pay (Tenant) or mark missed (Clerk) an installment | Tenant, Clerk |
| POST | `/hearings` | Schedule a hearing on a court calendar | Clerk |
| GET | `/hearings/{hearingId}` | Fetch a hearing | Clerk, Landlord, Tenant, Mediator, Judge |
| GET | `/hearings` | List hearings (filter by case/court/status/predecessor) | Clerk, Landlord, Tenant, Mediator, Judge |
| POST | `/hearings/{hearingId}/transition` | Hold (Judge), cancel (Clerk), or continue (Clerk) a hearing | Clerk, Judge |
| POST | `/judgments` | Enter a judgment (POSSESSION / DISMISSAL / DIVERSION) | Judge |
| GET | `/judgments/{judgmentId}` | Fetch a judgment | Clerk, Landlord, Tenant, Judge, Sheriff |
| GET | `/judgments` | List judgments (filter by case/status) | Clerk, Landlord, Tenant, Judge, Sheriff |
| POST | `/judgments/{judgmentId}/transition` | Judge stays, lifts, vacates, or satisfies a judgment | Judge |
| POST | `/lockout-orders` | Request a sheriff lockout under a possession judgment | Landlord, Clerk |
| GET | `/lockout-orders/{lockoutId}` | Fetch a lockout order | Clerk, Landlord, Tenant, Judge, Sheriff |
| GET | `/lockout-orders` | List lockout orders (filter by case/judgment/officer/status) | Clerk, Landlord, Tenant, Judge, Sheriff |
| POST | `/lockout-orders/{lockoutId}/transition` | Schedule, execute, or cancel a lockout | Sheriff, Clerk |
| POST | `/sealing-requests` | Request sealing/expungement of a closed case | Tenant |
| GET | `/sealing-requests/{sealingId}` | Fetch a sealing request | Clerk, Tenant, Judge |
| GET | `/sealing-requests` | List sealing requests (filter by case/status) | Clerk, Tenant, Judge |
| POST | `/sealing-requests/{sealingId}/transition` | Judge grants or denies a sealing request | Judge |

## 5. Error Code Catalogue

The trigger conditions for each error are described within the §2 and §3 narratives; this catalogue lists only the identifiers and their HTTP status codes.

| Error ID | HTTP Status Code |
| --- | --- |
| ERR_UNAUTHENTICATED | 401 |
| ERR_UNAUTHORIZED | 403 |
| ERR_VALIDATION | 422 |
| ERR_NOT_FOUND | 404 |
| ERR_STALE_VERSION | 412 |
| ERR_INVALID_STATE | 409 |
| ERR_ALREADY_ANSWERED | 409 |
| ERR_ANSWER_WINDOW_OPEN | 409 |
| ERR_ANSWER_WINDOW_CLOSED | 409 |
| ERR_NO_POSSESSION_JUDGMENT | 409 |
| ERR_CASE_NOT_IN_LITIGATION | 409 |
| ERR_SOD_VIOLATION | 409 |
| ERR_SEALING_INELIGIBLE | 409 |
| ERR_LOCKOUT_STAY_ACTIVE | 409 |
| ERR_LOCKOUT_NOT_DUE | 409 |
| ERR_INSTALLMENT_NOT_DUE | 409 |
| ERR_OFFICER_UNAVAILABLE | 409 |
| ERR_HEARING_CONFLICT | 409 |
| ERR_CALENDAR_FULL | 409 |
| ERR_INVALID_INTERVAL | 422 |
| ERR_PLAN_INSUFFICIENT | 409 |
| ERR_ASSISTANCE_BUDGET_EXCEEDED | 409 |
| ERR_NOT_DISBURSABLE | 409 |
| ERR_WRONG_PARTY_TURN | 409 |
