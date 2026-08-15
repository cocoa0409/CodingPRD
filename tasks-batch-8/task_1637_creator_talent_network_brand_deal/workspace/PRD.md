# Creator Talent Network API — Product Requirements Document

## 1. Introduction

The creator economy runs on negotiated trust: brands commit budget against a creator's audience, creators commit content against a brand's brief, and the agency sits in the middle underwriting both sides of that bargain. This document specifies the Creator Talent Network API, the platform on which such an agency runs its entire commercial operation — roster onboarding with audience-based rate cards, campaign brief publication and pitch negotiation, deal terms covering usage rights, category exclusivity, and paid-media whitelisting, content review with bounded revision rounds, advertising-disclosure compliance verification, performance measurement with bonus triggers, and finally invoicing, agency commission, and creator payout. A dispute and re-shoot policy governs what happens when the work product or the payment falls short.

Two design commitments shape every workflow that follows. First, money is never estimated twice: fees, commissions, bonuses, and late charges are produced by pinned formulas with pinned rounding order, and a figure pinned at its lifecycle moment does not drift afterward. Second, no party grades its own homework: the operator who approves content is never the officer who verifies its disclosure, and the administrator who issues an invoice is never the administrator who releases the payout it funds. All temporal behavior — submission windows, publish windows, exclusivity overlaps, invoice net terms, payout timing — reads a single logical clock rather than the wall clock, so every rule in this document is deterministic and reproducible.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

Every request must carry two mandatory HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. The platform recognizes exactly seven roles, spelled as follows: `PlatformAdmin`, `TalentManager`, `BrandManager`, `ComplianceOfficer`, `FinanceAdmin`, `Creator`, and `Brand`. A request that omits either header, or presents a role outside this list, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is not among the roles authorized for the target endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403).

Identity semantics differ by role, and the difference matters for ownership checks. When `X-User-Role` is `Creator`, the `X-User-ID` value is the `id` of the acting Creator record; ownership checks on any resource that references a creator compare the resource's `creator_id` field against `X-User-ID`. When `X-User-Role` is `Brand`, the `X-User-ID` value is the `id` of the acting Brand record, and ownership checks compare the resource's `brand_id` field against `X-User-ID`. An entity-backed caller that attempts to act on a resource it does not own is rejected with `ERR_FORBIDDEN`. When `X-User-Role` is `PlatformAdmin`, `TalentManager`, `BrandManager`, `ComplianceOfficer`, or `FinanceAdmin`, the `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server records it where a workflow demands an actor stamp — for example `reviewed_by_user_id` on a deliverable, `checked_by_user_id` on a disclosure check, `issued_by_user_id` on an invoice, or `released_by_user_id` on a payout — but never compares it to any entity's `id`. The segregation-of-duties rules in §2.10 compare these recorded operator identifiers against each other, not against entity records.

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

List endpoints paginate through two query parameters. The `limit` parameter sets the maximum number of items returned; when omitted it defaults to 10, and it may not be lower than 1 or higher than 100. The `offset` parameter sets the number of items skipped and defaults to 0. Unless otherwise specified, every list endpoint returns resources sorted by creation timestamp in ascending order.

The `meta` object of every list response carries four pagination fields: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties

All twelve resources in the platform — Creator, Brand, Brief, Pitch, Deal, Deliverable, DisclosureCheck, PerformanceReport, Invoice, Payout, Dispute, and Reshoot — share one set of system-managed properties:

- `id` (string): a unique, server-minted identifier formatted as a UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created.
- `updated_at` (string): an ISO 8601 UTC timestamp with three fractional digits refreshed on every mutation of the resource.
- `version` (integer): a system-managed integer that increments by exactly one on every mutation, including mutations performed by automatic system transitions and cascade side effects.

Every state transition, cascade step, bubble-up, and field update described in §3 therefore moves `updated_at` and `version` on each resource it touches, even when §3 names only the business effect.

### 2.5. The Logical Clock and Scheduled Sweeps

All temporal semantics in this document read a single logical clock maintained by the platform; no rule ever consults the wall clock. At startup the logical clock reads exactly 2026-08-01T00:00:00Z, and until the clock is first set it continues to read that default — there is no silent fallback to real time. A `PlatformAdmin` advances the clock through an admin-only test-driving capability that accepts a `to_iso8601` instant and reports the resulting `current_utc`.

Advancing the clock is never a passive act: each clock-set triggers two sweeps. First, every brief still `OPEN` whose `submission_window_end` lies behind the new clock reading transitions to `EXPIRED`, withdrawing its unresolved pitches as described in §3.2. Second, every invoice still `ISSUED` whose `due_date` lies behind the new clock reading transitions to `OVERDUE`, exposing it to the late-fee accrual of §3.8. Publish windows, payout release gates, exclusivity overlaps, and measurement periods all evaluate against the same logical clock.

### 2.6. Money, Basis Points, and Rounding Discipline

Every monetary value in the system is an integer count of cents; no fractional cents exist at rest or in transit. Rates that would naturally be percentages — creator engagement, agency commission — are carried as integer basis points, so a value of 400 means 4.00%. Percentages that participate directly in formulas (the service fee, the volume discount, the usage add-on, the exclusivity uplift, the late fee) are applied as exact decimal factors stated alongside each rule.

Rounding is pinned per calculation, and the default is round half up to the nearest whole cent. The single exception is the engagement-rate derivation inside the performance bonus, which rounds half down to a whole basis point. Where a document carries several money lines, each line is rounded to whole cents first and the rounded lines are then summed; summing unrounded intermediates and rounding the total is explicitly forbidden because it yields different cents.

### 2.7. Optimistic Concurrency Control

Three write operations mutate a parent aggregate whose terms other clients may already have observed, and each therefore carries a mandatory optimistic-concurrency field:

- Creating a pitch against a brief requires `expected_brief_version`, carrying the brief's current `version` as last observed by the caller. Pitch creation mutates the brief — it can supersede the same creator's prior `SUBMITTED` pitch and it advances the brief's `version` — so a writer holding a stale brief version would silently supersede work on terms it never saw. A mismatch with the brief's current `version` is rejected with `ERR_STALE_VERSION` (HTTP 412).
- Proposing deal terms requires `expected_deal_version`, carrying the deal's current `version` as last observed by the caller. A new proposal supersedes the prior draft terms, so a stale writer would overwrite terms the counterparty may already have read. A mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412).
- Submitting a performance report requires `expected_deal_version` on the same terms: submission supersedes any `REPORTED` report with an overlapping period, so a stale writer would supersede reports it never observed. A mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412).

The version field on these three operations is non-optional. No other endpoint accepts or requires a version field.

### 2.8. Validation Order and Error Precedence

A single request can violate several rules at once, so checks fire in a fixed global order and the first failing check determines the response. The order is:

1. Authentication: both headers present and the role declared (else `ERR_UNAUTHENTICATED`).
2. Role authorization: the acting role appears in the endpoint's authorized list (else `ERR_FORBIDDEN`).
3. Ownership: an entity-backed `Creator` or `Brand` caller acts only on resources whose `creator_id` or `brand_id` equals `X-User-ID` — this governs creator responses, brand responses, deliverable submission and publishing, disclosure requeues, reshoot responses, dispute creation, and scoped reads (else `ERR_FORBIDDEN`).
4. Existence: path resources exist, validated left to right (else `ERR_NOT_FOUND`).
5. Payload well-formedness: required fields present, enums valid, ranges valid — `period_end` later than `period_start`, `audited_views` not exceeding `views`, `reduction_pct` strictly between zero and one (else `ERR_VALIDATION`).
6. Optimistic concurrency: the `expected_brief_version` or `expected_deal_version` matches the parent's current `version` (else `ERR_STALE_VERSION`).
7. Terminal lockdown: the action was triggered from a terminal state (else `ERR_ALREADY_TERMINAL`).
8. State precondition: the entity is not in a state the transition allows (else `ERR_INVALID_STATE`).

Once those eight gates pass, the business rules fire, also in a fixed order: segregation of duties (`ERR_SEGREGATION_OF_DUTIES`); the compliance-strike gate on publishing (`ERR_CREATOR_COMPLIANCE_SUSPENDED`); the unresolved-disclosure gate on payout release (`ERR_DISCLOSURE_NOT_PASSED`); exclusivity overlap (`ERR_EXCLUSIVITY_CONFLICT`); publish spacing between sibling deliverables (`ERR_PUBLISH_GAP_VIOLATION`); deliverable count (`ERR_DELIVERABLE_COUNT_EXCEEDED`); revision limits (`ERR_REVISION_LIMIT_EXCEEDED`); reshoot limits (`ERR_RESHOOT_LIMIT_EXCEEDED`); negotiation round caps (`ERR_NEGOTIATION_LIMIT_EXCEEDED`); brief slot capacity (`ERR_BRIEF_SLOTS_FULL`); pitch eligibility (`ERR_PITCH_REQUIREMENTS_NOT_MET`); duplicate report periods (`ERR_DUPLICATE_REPORT_PERIOD`); the one-open-invoice rule (`ERR_INVOICE_ALREADY_EXISTS`); the creator-exit block (`ERR_ACTIVE_DEALS_EXIST`); the submission window (`ERR_SUBMISSION_WINDOW_CLOSED`); the publish window (`ERR_PUBLISH_WINDOW_VIOLATION`); payout timing (`ERR_PAYOUT_NOT_DUE`); creator-active requirements (`ERR_CREATOR_NOT_ACTIVE`); brand-active requirements (`ERR_BRAND_SUSPENDED`); brand credit hold (`ERR_BRAND_CREDIT_HOLD`); the brief budget (`ERR_BRIEF_BUDGET_EXCEEDED`); and finally the payment-amount match (`ERR_PAYMENT_AMOUNT_MISMATCH`).

The practical consequence: on an endpoint guarded by several business rules, a caller always sees the same error first. Activating a deal that would both violate exclusivity and breach a credit hold surfaces `ERR_EXCLUSIVITY_CONFLICT`; releasing a payout before its due date while disclosures remain unresolved surfaces `ERR_DISCLOSURE_NOT_PASSED`, because the disclosure gate outranks the timing gate.

### 2.9. State Machines, Terminal Lockdown, and Cross-Entity Consistency

Every resource has a declared lifecycle. Terminal states are: `EXITED` for a Creator; `EXPIRED` and `CLOSED` for a Brief; `ACCEPTED`, `REJECTED`, `WITHDRAWN`, and `SUPERSEDED` for a Pitch; `COMPLETED` and `TERMINATED` for a Deal; `VERIFIED` and `CANCELLED` for a Deliverable; `PASSED`, `ESCALATED`, and `VOIDED` for a DisclosureCheck; `FINAL` and `SUPERSEDED` for a PerformanceReport; `PAID` and `VOID` for an Invoice; `PAID`, `VOIDED`, and `CLAWED_BACK` for a Payout; `RESOLVED_UPHELD` and `RESOLVED_DISMISSED` for a Dispute; and `ACCEPTED` and `DECLINED` for a Reshoot. The Brand lifecycle (`ACTIVE` and `SUSPENDED`) has no terminal state.

Triggering an action from a terminal state is rejected with `ERR_ALREADY_TERMINAL` (HTTP 409); triggering one from a non-terminal state the transition does not allow is rejected with `ERR_INVALID_STATE` (HTTP 409). The two errors are distinct: the first means the lifecycle is closed, the second means the requested move is not an edge of the machine.

State changes propagate. Cascades flow downward — suspending a creator withdraws that creator's open pitches, terminating a deal cancels its deliverables and claws back its payouts — and bubble-ups flow upward: a pitch acceptance can auto-award its brief, a disclosure pass verifies its deliverable, and a deliverable verification can complete its deal. The server performs these automatic transitions without an explicit client request on the affected resource, and each affected resource observes the mutation rules of §2.4.

### 2.10. Segregation of Duties

Two controlled handoffs require two different people. The `ComplianceOfficer` who reviews a deliverable's disclosure check must not be the operator recorded as that deliverable's `reviewed_by_user_id` — the person who approved the content for publication. The `FinanceAdmin` who releases a payout must not be the operator recorded as the funding invoice's `issued_by_user_id`. Both violations are rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403), and both compare the acting `X-User-ID` against the recorded actor stamp.

### 2.11. Nested Resource Retrieval

Requests that target nested resources validate path identifiers sequentially, left to right, and reject with `ERR_NOT_FOUND` (HTTP 404) at the first identifier that does not resolve. A request for the pitches of a brief that does not exist, for example, reports the missing brief before any pitch-level question is considered; a request for a deliverable under a missing deal reports the missing deal.

## 3. Business Logic & Workflows

### 3.1. Roster Intake, Rate Cards, and Creator Standing

A `TalentManager` onboards each creator with a unique `handle`, a contact `email`, a content `niche` (one of `BEAUTY`, `FASHION`, `TECH`, `FINANCE`, `GAMING`, `FITNESS`, `FOOD`, `TRAVEL`, or `OTHER`), a `primary_platform` (one of `YOUTUBE`, `INSTAGRAM`, `TIKTOK`, or `TWITCH`), and three audience metrics: `followers`, `avg_views_30d` (the average views per post over the trailing thirty days), and `engagement_rate_bps`. Each metric is a non-negative integer. A newly onboarded creator lands in `APPLIED`, the first state of a lifecycle that runs `APPLIED` → `SCREENING` → `ACTIVE`, with `SUSPENDED` as a standing penalty and `EXITED` as the only terminal state.

Moving a creator from `APPLIED` to `SCREENING` is a plain lifecycle call carrying `to_state`. Promotion from `SCREENING` to `ACTIVE` is gated on data readiness: all three audience metrics must be set, because activation runs the rate-card computation that prices the creator's inventory. The same computation re-runs on every audience-metrics update, which carries `followers`, `avg_views_30d`, and `engagement_rate_bps` and bumps the creator's `version`.

The rate card works as follows. The base CPM tiers on `followers`: fewer than 10,000 followers prices at 1,500 cents; at least 10,000 but fewer than 100,000 prices at 2,200 cents; at least 100,000 but fewer than 1,000,000 prices at 3,000 cents; and 1,000,000 followers or more prices at 4,500 cents. An engagement multiplier then applies, keyed on `engagement_rate_bps`: below 100 basis points the multiplier is 0.80; below 300 it is 1.00; below 600 it is 1.15; and at 600 basis points or more it is 1.30. A niche multiplier applies next: 1.20 for `FINANCE` or `TECH`, 1.10 for `BEAUTY` or `FASHION`, and 1.00 for every other niche. The `rate_card_cpm_cents` is the base CPM multiplied by the engagement multiplier and then by the niche multiplier, rounded half up to whole cents. The `rate_card_flat_cents` — the per-deliverable flat fee — is `rate_card_cpm_cents` multiplied by `avg_views_30d` and divided by one thousand, rounded half up to whole cents, and then raised to a floor of 50,000 cents whenever the computed value falls below that floor.

Three standing counters track a creator's commercial and compliance posture. `compliance_strikes`, initially zero, counts `ESCALATED` disclosure checks on the creator's deliverables; when the count reaches three the creator is suspended automatically, and a `TalentManager` may also suspend an `ACTIVE` creator directly. Either path — manual or automatic — moves the creator from `ACTIVE` to `SUSPENDED` and withdraws every pitch of that creator still sitting in `SUBMITTED`, `SHORTLISTED`, or `COUNTERED`. Reinstating a `SUSPENDED` creator back to `ACTIVE` resets `compliance_strikes` to zero. The `lifetime_billed_cents` counter, also initially zero, accumulates the `fee_line_cents` of every invoice on the creator's deals that reaches `PAID`; it is updated by the record-payment cascade of §3.8 and drives the commission tiers of the payout settlement. The `pending_disclosure_count` reflects how many disclosure checks on the creator's deliverables currently sit in `QUEUED` or `FAILED`, and is recomputed whenever such a check is created, passed, escalated, or voided.

A creator leaves the roster by moving from `ACTIVE` or `SUSPENDED` to `EXITED` — but only while no deal naming that creator sits outside `COMPLETED` or `TERMINATED`; an exit attempted over live deals is rejected with `ERR_ACTIVE_DEALS_EXIST`.

### 3.2. Brand Accounts and Campaign Briefs

A `BrandManager` onboards a brand with its legal `name` and an `industry` (one of `CPG`, `TECH`, `FINANCE`, `FASHION`, `AUTOMOTIVE`, `GAMING`, or `OTHER`). A brand account opens in `ACTIVE` standing and can later be moved to `SUSPENDED` and back through a brand update, which may also set `credit_hold`. When `credit_hold` is true — it starts false — two operations are blocked with `ERR_BRAND_CREDIT_HOLD` (HTTP 402): publishing a brief and activating a deal. The brand's `outstanding_balance_cents` is a ledger mirror, maintained by the invoice workflows of §3.8: it rises by an invoice's `total_cents` when the invoice is issued, falls by `total_cents` when payment is recorded, and falls again by `total_cents` when an issued invoice is voided — so it always equals the sum of `total_cents` across the brand's invoices in `ISSUED` or `OVERDUE`.

A campaign brief is the brand's purchase order for creator inventory. Its creation payload carries the owning `brand_id`; a `title`; a target `niche` drawn from the same nine-value enum as the creator's; eligibility thresholds `min_followers` and `min_engagement_bps`, both non-negative; a `slots_total` of at least one funded creator slot; a positive `budget_cents` cap on committed pitch fees; a `deliverables_per_slot` of at least one; `usage_rights_days` of at least one, the number of days the brand may reuse each deliverable; an `exclusivity_category` (one of `NONE`, `BEVERAGES`, `SNACKS`, `SKINCARE`, `SOFTWARE`, `FINTECH`, `AUTOMOTIVE`, `GAMING`, or `APPAREL`); an `exclusivity_days` window length that may be zero and is ignored entirely when the category is `NONE`; an optional `whitelisting_required` flag defaulting to false; an optional `revision_rounds_included` defaulting to two; and four datetimes bounding the campaign — `submission_window_start` and `submission_window_end` bracket when pitches are accepted, `content_window_start` and `content_window_end` bracket when deliverables may publish. Both window starts must fall at or before their corresponding ends, and a brief that inverts either window is rejected with `ERR_VALIDATION`. Brief creation is refused with `ERR_BRAND_SUSPENDED` when the owning brand is not `ACTIVE`. A new brief opens in `DRAFT`.

Publishing moves the brief from `DRAFT` to `OPEN` and re-checks the brand's standing: the brand must still be `ACTIVE` (else `ERR_BRAND_SUSPENDED`) and must not sit on credit hold (else `ERR_BRAND_CREDIT_HOLD`). Once `OPEN`, the brief accepts pitches until the logical clock passes `submission_window_end`, at which point the clock sweep moves it to `EXPIRED` and withdraws every pitch still in `SUBMITTED`, `SHORTLISTED`, or `COUNTERED`.

Slot accounting on the brief is automatic. The `slots_committed` counter tracks how many of the brief's pitches are in `ACCEPTED` with a deal that has not been `TERMINATED`; it is recomputed upward on every pitch acceptance and downward whenever such a deal terminates. When an acceptance lifts `slots_committed` to equal `slots_total`, the brief bubble-up transitions from `OPEN` to `AWARDED` on its own. A `BrandManager` closes a brief explicitly: an `OPEN` brief closes only while `slots_committed` is still zero — otherwise the close is rejected with `ERR_INVALID_STATE` — and closing it withdraws the same trio of unresolved pitch states; an `AWARDED` brief closes once every deal it spawned has reached `COMPLETED` or `TERMINATED`. `EXPIRED` and `CLOSED` are terminal.

### 3.3. Pitching, Counters, and Slot Allocation

A `TalentManager` pitches a creator onto a brief with a payload naming the `creator_id`, a positive `proposed_fee_cents` (the base fee, before usage, exclusivity, or whitelisting adjustments), a free-text `concept_note`, and the `expected_brief_version` concurrency field of §2.7. The gate sequence matters: after the shared auth, existence, well-formedness, and concurrency checks of §2.8, pitch eligibility fires first — the creator's `followers` must be at least the brief's `min_followers` and the creator's `engagement_rate_bps` at least the brief's `min_engagement_bps`, with exactly meeting a threshold qualifying, else `ERR_PITCH_REQUIREMENTS_NOT_MET`; next the submission window — the logical clock must read at or after `submission_window_start` and at or before `submission_window_end`, both bounds inclusive, else `ERR_SUBMISSION_WINDOW_CLOSED`; and finally the creator must currently be `ACTIVE`, else `ERR_CREATOR_NOT_ACTIVE`.

Pitch creation mutates the brief as well as creating the pitch: the brief's `version` advances by one, and if the same creator already holds a `SUBMITTED` pitch on this brief, that prior pitch auto-transitions to `SUPERSEDED` with its `superseded_by_pitch_id` pointing at the new pitch and its own `version` advancing. The new pitch opens in `SUBMITTED` with `negotiation_rounds` at zero and `deal_id` still null.

From there the brand side drives the pitch through an `action` payload carrying one of four values. Shortlisting moves `SUBMITTED` → `SHORTLISTED` and requires the brief still `OPEN`, else `ERR_INVALID_STATE`. Countering, carrying `counter_fee_cents`, moves `SHORTLISTED` → `COUNTERED`: the pitch's `proposed_fee_cents` is overwritten with the counter value and `negotiation_rounds` increments; a counter attempted after the pitch has consumed three negotiation rounds is rejected with `ERR_NEGOTIATION_LIMIT_EXCEEDED`. Rejecting moves a pitch from `SUBMITTED`, `SHORTLISTED`, or `COUNTERED` to terminal `REJECTED`. Accepting is the load-bearing action and is detailed below. The talent side answers through the same `action` field with two values of its own: resubmitting, carrying a fresh `proposed_fee_cents`, moves `COUNTERED` → `SHORTLISTED` while the brief is `OPEN` and rounds remain — the same three-round cap and the same `ERR_NEGOTIATION_LIMIT_EXCEEDED` apply — and withdrawing moves a pitch from any of `SUBMITTED`, `SHORTLISTED`, or `COUNTERED` to terminal `WITHDRAWN`.

Acceptance by a `BrandManager` requires the pitch to be `SHORTLISTED`, and its brief must be `OPEN` or `AWARDED` — any other brief state is rejected with `ERR_INVALID_STATE`. Capacity is checked next: when `slots_committed` already equals `slots_total`, acceptance is rejected with `ERR_BRIEF_SLOTS_FULL`. The budget check follows: the sum of `proposed_fee_cents` across the brief's `ACCEPTED` pitches whose deals are not `TERMINATED`, plus this pitch's `proposed_fee_cents`, must not exceed the brief's `budget_cents`, else `ERR_BRIEF_BUDGET_EXCEEDED`. On success, acceptance creates the Deal in `DRAFT`: the deal records the originating `pitch_id` one-to-one, denormalizes `brief_id` and `creator_id` from the pitch and `brand_id` from the brief, and copies the brief's commercial terms — `usage_rights_days`, `exclusivity_category`, `exclusivity_days`, `whitelisting` (copied from `whitelisting_required`), and `revision_rounds_included` — while its `fee_base_cents` starts at the pitch's `proposed_fee_cents`. The pitch's `deal_id` is set to the new deal, `slots_committed` is recomputed upward by one, and when that brings the count level with `slots_total` the brief auto-transitions to `AWARDED`. `ACCEPTED` is terminal for the pitch.

### 3.4. Deal Negotiation, Activation, and Exclusivity

A deal born from pitch acceptance starts in `DRAFT` and is not yet visible to its counterparty as a firm offer. A `BrandManager` puts terms on the table by proposing them with a positive `fee_base_cents` and the mandatory `expected_deal_version` of §2.7; a version mismatch is rejected with `ERR_STALE_VERSION`. The proposal moves the deal from `DRAFT` to `PENDING_CREATOR`, records the fee, and increments `terms_version` — the counter that pins exactly which generation of terms each party later accepted, since every proposal bumps it.

The creator answers first through an `action` of `ACCEPT`, `COUNTER`, or `DECLINE`, and must be the deal's own creator: the acting `X-User-ID` must equal the deal's `creator_id`. An `ACCEPT` advances the deal from `PENDING_CREATOR` to `PENDING_BRAND`. A `COUNTER`, carrying `counter_fee_cents`, returns the deal to `DRAFT` and consumes one of four allowed deal-negotiation rounds — a counter beyond that cap is rejected with `ERR_NEGOTIATION_LIMIT_EXCEEDED` — leaving the next proposal to set the new `fee_base_cents`. A `DECLINE` terminates the deal outright and recomputes the brief's `slots_committed` downward by one.

The brand then answers in kind through its own `action` value, acting as the deal's own brand — the acting `X-User-ID` must equal the deal's `brand_id`. A brand `COUNTER` from `PENDING_BRAND` likewise returns the deal to `DRAFT` under the same four-round cap, and a brand `DECLINE` terminates with the same downward slot recompute. A brand `ACCEPT` is activation, and activation carries the heaviest gate in the system. Its checks fire in the §2.8 order: the deal must be `PENDING_BRAND` (else `ERR_INVALID_STATE`); then the exclusivity scan; then the credit-hold check, which rejects with `ERR_BRAND_CREDIT_HOLD` when the brand's `credit_hold` is true.

The exclusivity scan protects category conflicts across the creator's whole portfolio. Activation is rejected with `ERR_EXCLUSIVITY_CONFLICT` when any other deal with the same `creator_id` is `ACTIVE` in the same non-`NONE` `exclusivity_category` and its exclusivity window overlaps the candidate window this activation would open. Every exclusivity window is a half-open interval that includes its `exclusive_window_start` instant and excludes its `exclusive_window_end` instant, so two windows that merely touch — one ending exactly when the other begins — do not conflict. When the category is `NONE` the window fields stay null and the scan can never conflict.

On a successful activation the platform pins the money. The final fee is computed in a fixed sequence and stored on `fee_total_cents`, which is null until this moment. First, the base sum is the creator's current `rate_card_flat_cents` multiplied by the brief's `deliverables_per_slot`. Second, when `deliverables_per_slot` is three or more, a ten-percent multi-deliverable discount applies: the base after discount is the base sum multiplied by 0.90, rounded half up to whole cents; with fewer than three deliverables the base after discount equals the base sum. Third, the usage add-on tiers on `usage_rights_days`: thirty days or fewer adds nothing; ninety days or fewer adds ten percent of the base after discount; three hundred sixty-five days or fewer adds twenty-five percent; anything longer adds fifty percent — the add-on itself rounded half up to whole cents. Fourth, when the deal's `whitelisting` is set, a whitelisting add-on of 75,000 cents per deliverable applies — 75,000 cents multiplied by `deliverables_per_slot` — otherwise zero. Fifth, the provisional subtotal is the base after discount plus the usage add-on plus the whitelisting add-on. Sixth, the exclusivity uplift: zero when `exclusivity_category` is `NONE`; otherwise five percent when the subtotal is below 500,000 cents, twelve percent when it is below 2,000,000 cents, and twenty percent at 2,000,000 cents or more — the tier keyed on the subtotal that already includes both add-ons, which is what makes the self-reference well-defined. Finally, `fee_total_cents` is the subtotal multiplied by one plus the uplift percentage, rounded half up to whole cents. The negotiated `fee_base_cents` remains recorded on the deal as the audit reference; the computed fee deliberately prices off the creator's rate card, not off the negotiation. Activation also stamps `activated_at` from the logical clock, sets `exclusive_window_start` to that same instant, and sets `exclusive_window_end` to `activated_at` plus `exclusivity_days` — both window fields remaining null when the category is `NONE`.

A deal in `ACTIVE` completes itself: when the last of its deliverables reaches `VERIFIED` — every deliverable of the deal verified, with at least one deliverable existing — the deal bubble-up transitions to `COMPLETED`. Termination is the hard stop and may be invoked by a `BrandManager` on an `ACTIVE` deal with a free-text `reason`. Termination cascades in a pinned order: every deliverable not already `VERIFIED` or `CANCELLED` moves to `CANCELLED`, leaving verified work untouched; each cancelled deliverable voids its disclosure checks sitting in `QUEUED` or `FAILED`; each voiding recomputes the creator's `pending_disclosure_count`; every invoice of the deal in `DRAFT`, `ISSUED`, or `OVERDUE` moves to `VOID` with `void_reason` recorded as DEAL_TERMINATED, and the brand's `outstanding_balance_cents` is reduced by each such invoice's `total_cents` — `PAID` invoices are untouched; every payout of the deal in `ACCRUED`, `PAYABLE`, or `HELD` moves to `CLAWED_BACK`; and the brief's `slots_committed` is recomputed downward by one. `COMPLETED` and `TERMINATED` are terminal.

### 3.5. Content Production and Review Cycles

Deliverables are planned by a `BrandManager` against an `ACTIVE` deal; planning against a deal in any other state is rejected with `ERR_INVALID_STATE`. Each planned deliverable names a `platform` (`YOUTUBE`, `INSTAGRAM`, `TIKTOK`, or `TWITCH`), a `due_date` that is informational only, and a `scheduled_publish_date` marking the intended publish instant. Two spacing rules guard the plan: the new deliverable's `scheduled_publish_date` must sit at least 48 hours away from the `scheduled_publish_date` of every sibling deliverable on the same deal, else `ERR_PUBLISH_GAP_VIOLATION`; and the deal may not carry more non-`CANCELLED` deliverables than the brief's `deliverables_per_slot` — planning beyond that count is rejected with `ERR_DELIVERABLE_COUNT_EXCEEDED`. A planned deliverable opens in `PENDING_SUBMISSION` with `revision_rounds_used` and `reshoot_count` at zero.

Submission belongs to the deal's creator and moves the deliverable from `PENDING_SUBMISSION` — or, after a change request, from `REVISION_REQUESTED` — into `IN_REVIEW`; the deal must still be `ACTIVE`. Review belongs to a `BrandManager`, whose review call carries an `action` of `APPROVE` or `REQUEST_REVISION`. Approving moves `IN_REVIEW` → `APPROVED` and stamps the deliverable's `reviewed_by_user_id` with the acting operator's `X-User-ID` — the stamp that later anchors the disclosure segregation check. Requesting a revision, with an optional `note`, moves `IN_REVIEW` → `REVISION_REQUESTED` and increments `revision_rounds_used`; a request made when `revision_rounds_used` has already reached the deal's `revision_rounds_included` is rejected with `ERR_REVISION_LIMIT_EXCEEDED`.

Publishing returns to the creator and is the safety-critical step. The deliverable must be `APPROVED`, the deal must be `ACTIVE`, and the acting creator must own the deal. Two further gates fire in §2.8 order: the creator must be in good compliance standing — `ACTIVE` with `compliance_strikes` below the three-strike limit, else `ERR_CREATOR_COMPLIANCE_SUSPENDED` — and the logical clock must read at or after the brief's `content_window_start` and at or before its `content_window_end`, both bounds inclusive, else `ERR_PUBLISH_WINDOW_VIOLATION`. A successful publish records the payload's `content_url` on the deliverable, stamps `published_at` from the logical clock, spawns a disclosure check in `QUEUED` for the deliverable, and lifts the creator's `pending_disclosure_count` by one.

Verification is a bubble-up, covered with the compliance workflow in §3.6: a passed disclosure check moves the deliverable from `PUBLISHED` to `VERIFIED`, stamps `verified_at`, drops the creator's `pending_disclosure_count` by one, and — when every deliverable of the deal is now `VERIFIED` — completes the deal. `VERIFIED` and `CANCELLED` are terminal for a deliverable, though §3.9's re-shoot mechanism can deliberately reopen even a verified deliverable.

### 3.6. Disclosure Verification and Compliance Enforcement

Advertising-disclosure compliance is enforced per deliverable, by an independent `ComplianceOfficer`, against a three-item checklist. Every disclosure check references its `deliverable_id` and opens in `QUEUED` the moment the deliverable publishes, with `recheck_count` at zero. The checklist payload records `has_ad_hashtag` (an #ad marker or equivalent present), `verbal_disclosure` (a spoken or audio disclosure present), and `platform_tool_used` (the platform's paid-partnership tool enabled); each flag defaults to false, and a recorded review stamps `checked_by_user_id` with the reviewing officer's `X-User-ID` and `checked_at` with the logical clock.

The officer's review carries an `action` of `PASS` or `FAIL` alongside the checklist. Recording `PASS` on a queued check requires two things, evaluated in §2.8 order. All three checklist flags must be true — a pass recorded with any flag false is rejected with `ERR_VALIDATION` — and the reviewing officer must not be the operator who approved the content: the acting `X-User-ID` must differ from the deliverable's `reviewed_by_user_id`, else `ERR_SEGREGATION_OF_DUTIES`. A passed check lands in terminal `PASSED` and bubbles upward as §3.5 describes: the deliverable verifies, and through it the deal may complete.

Failing is graduated. Recording `FAIL` while the check's `recheck_count` is below two moves the check to `FAILED`, from which the deal's creator — and only the deal's creator — may requeue it after fixing the content: requeueing returns the check from `FAILED` to `QUEUED` and increments `recheck_count`. A `FAIL` recorded when `recheck_count` has already reached two does not produce another `FAILED` cycle; it moves the check to terminal `ESCALATED` and fires the enforcement cascade: the creator's `compliance_strikes` increments by one, the creator's `pending_disclosure_count` is recomputed downward by one, and when the strike count reaches three the creator auto-transitions to `SUSPENDED` — which in turn withdraws every pitch of that creator still in `SUBMITTED`, `SHORTLISTED`, or `COUNTERED`, three cascade links deep from the original review. Checks may also be voided without a review: when a deliverable is cancelled or reset by an accepted re-shoot, its checks in `QUEUED` or `FAILED` move to terminal `VOIDED`, and each voiding recomputes the creator's `pending_disclosure_count` downward by one.

### 3.7. Performance Reporting and Bonus Accrual

Once a deal is live, a `BrandManager` reports performance against it. Submission requires the deal to be `ACTIVE` or `COMPLETED` — any other deal state is rejected with `ERR_INVALID_STATE` — and carries the measurement window `period_start` and `period_end`, the window including its start instant and excluding its end, with `period_end` strictly later than `period_start`; the raw counters `views`, `likes`, `comments`, and `shares`, each a non-negative integer; and the mandatory `expected_deal_version` of §2.7. Two period rules apply. A new report whose window overlaps — any intersection at all — a `FINAL` report of the same deal is rejected with `ERR_DUPLICATE_REPORT_PERIOD`. A new report whose window overlaps a still-`REPORTED` report of the same deal supersedes it: the prior report moves to terminal `SUPERSEDED` and its `version` advances.

The submission itself computes `provisional_bonus_cents` on the raw metrics — the optimistic PROVISIONAL variant of the bonus, which prices unaudited, possibly bot-inflated views. The bonus works as follows. The view tier pays the highest qualifying tier only, never cumulatively: at least 5,000,000 views pays 400,000 cents; failing that, at least 1,000,000 views pays 100,000 cents; failing that, at least 250,000 views pays 25,000 cents; below every tier it pays zero. An engagement kicker then applies. The engagement rate in basis points is zero when the measured view count is zero, and otherwise is the sum of likes, comments, and shares multiplied by ten thousand and divided by the view count, rounded half down to a whole basis point. When that rate reaches at least 400 basis points, the tier bonus is multiplied by 1.25 and rounded half up to whole cents; otherwise the tier bonus stands unchanged.

Finalization replaces optimism with audit. A `BrandManager` finalizes a `REPORTED` report by supplying `audited_views` — a non-negative integer that may not exceed the reported `views`, else `ERR_VALIDATION` — and `audited_engagements`, a single non-negative, bot-filtered engagement total that stands in for the raw likes-comments-shares sum. The report moves from `REPORTED` to terminal `FINAL`, the FINAL bonus variant runs the identical tier-and-kicker formula on `audited_views` and `audited_engagements`, and the result lands on `final_bonus_cents`, which is null until this moment. When the audit discounts views across a tier boundary, the FINAL figure lands below the PROVISIONAL one. Finalization also recomputes the deal's `bonus_accrued_cents`: the sum of `final_bonus_cents` across the deal's `FINAL` reports that have not yet been billed on a non-`VOID` invoice — the figure the invoice workflow of §3.8 draws into its bonus line.

### 3.8. Invoicing, Collections, and Payout Settlement

Billing belongs to `FinanceAdmin`. An invoice is created against a deal that is `ACTIVE` or `COMPLETED` and carries at least one `VERIFIED` deliverable — any other posture is rejected with `ERR_INVALID_STATE` — and a deal may hold at most one non-`VOID` invoice at a time, so a second live invoice is rejected with `ERR_INVOICE_ALREADY_EXISTS`. The invoice denormalizes its `brand_id` from the deal and computes its lines at creation, in a pinned order: each line is rounded half up to whole cents first, and the rounded lines are then summed — summing first and rounding once is forbidden. The `fee_line_cents` is the deal's `fee_total_cents` multiplied by one minus the deal's `reduction_pct` — a figure that starts at zero and moves only through an upheld fee-reduction dispute — rounded half up. The `service_line_cents` is five percent of that same reduced fee — the deal's `fee_total_cents` multiplied by one minus `reduction_pct` and by 0.05 — rounded half up; this line is agency revenue and never reaches the creator. The `bonus_line_cents` copies the deal's `bonus_accrued_cents` at creation time, already a whole-cent figure. The `total_cents` is the sum of the three rounded lines. A fresh invoice sits in `DRAFT` with `late_fee_cents` at zero and `issued_at`, `due_date`, and `paid_at` still null.

Issuing moves `DRAFT` → `ISSUED`: `issued_at` is stamped from the logical clock, `due_date` falls exactly thirty days after `issued_at`, `issued_by_user_id` records the issuing operator, and the brand's `outstanding_balance_cents` rises by `total_cents`. Issuing also spawns the deal's payout in `ACCRUED`, referencing the funding `invoice_id` and denormalizing `deal_id` and the payee `creator_id`. The payout's `gross_cents` is the invoice's `fee_line_cents` plus its `bonus_line_cents` — creator earnings, excluding the service line — and its commission fields are first pinned with the ESTIMATED variant of the commission split described below.

Collection works against the clock. When a clock advance carries time past an `ISSUED` invoice's `due_date`, the sweep moves it to `OVERDUE`. Payment may be recorded against an invoice in `ISSUED` or `OVERDUE` — an invoice in any other state has nothing to collect. Recording payment accepts an `amount_cents` and demands exactness: the amount must equal the invoice's `total_cents` plus its `late_fee_cents`, else `ERR_PAYMENT_AMOUNT_MISMATCH`. The late fee accrues only on an `OVERDUE` invoice and is computed chronologically: the days overdue are the elapsed seconds between `due_date` and the payment instant divided by 86,400 and rounded up to a whole day — zero when payment is not after the due date; the started periods are the days overdue divided by seven and rounded up, so one day overdue bills one period, exactly seven days still bills one, and eight days bills two; the `late_fee_cents` is then `total_cents` multiplied by 1.5 percent and by the number of started periods, rounded half up to whole cents. A recorded payment stamps `paid_at` from the logical clock, drops the brand's `outstanding_balance_cents` by `total_cents`, and fires two cascade links: the invoice's payout moves from `ACCRUED` to `PAYABLE` with `payout_due_at` set to exactly seven days after `paid_at`, and the creator's `lifetime_billed_cents` rises by the invoice's `fee_line_cents` — an increment that may push the creator across a commission tier boundary.

Voiding is the compensating path, takes a mandatory `void_reason`, and is allowed from `DRAFT` or `ISSUED`. Voiding a `DRAFT` invoice is a plain terminal transition — nothing was ever owed. Voiding an `ISSUED` invoice posts the compensating entry: the brand's `outstanding_balance_cents` falls by `total_cents`, netting the issue to zero, and the invoice's payout moves from `ACCRUED` to `VOIDED`. `PAID` and `VOID` are terminal.

Release settles the creator. A payout releases only from `PAYABLE`, and its gate fires in §2.8 order: the acting `X-User-ID` must differ from the funding invoice's `issued_by_user_id`, else `ERR_SEGREGATION_OF_DUTIES`; no disclosure check on any of the deal's deliverables may sit in `QUEUED` or `FAILED`, else `ERR_DISCLOSURE_NOT_PASSED`; and the logical clock must read at or after `payout_due_at` — a reading exactly equal to the due instant is allowed — else `ERR_PAYOUT_NOT_DUE`. Release re-pins the commission with the SETTLEMENT variant, stamps `released_by_user_id` and `released_at`, and lands the payout in terminal `PAID`.

The commission split tiers on the creator's cumulative billing. The rate is 2,000 basis points — twenty percent — while the creator's `lifetime_billed_cents` sits below 5,000,000 cents; 1,500 basis points while it sits below 20,000,000 cents; and 1,200 basis points at 20,000,000 cents or more. The `commission_cents` is `gross_cents` multiplied by the rate in basis points and divided by ten thousand, rounded half up to whole cents, and the `net_cents` is `gross_cents` minus `commission_cents`. The two variants differ only in what the tier sees: the ESTIMATED pinning at invoice issue reads `lifetime_billed_cents` excluding this invoice, which has not yet been paid, while the SETTLEMENT pinning at release reads it including this invoice's `fee_line_cents`, added at record-payment — so settlement can cross a tier boundary and land on a lower rate than the estimate. The re-pinned `commission_rate_bps`, `commission_cents`, and `net_cents` replace the estimated figures at release.

Finance retains manual control between the fixed points. A `FinanceAdmin` may hold a payout in `ACCRUED` or `PAYABLE`, moving it to `HELD`, and may unhold a `HELD` payout, which restores it to `PAYABLE` when `payout_due_at` is already set — meaning the invoice was paid — and to `ACCRUED` when it is not. Raising a dispute holds the deal's `ACCRUED` and `PAYABLE` payouts automatically, as §3.9 describes, and deal termination claws every `ACCRUED`, `PAYABLE`, or `HELD` payout back to terminal `CLAWED_BACK`.

### 3.9. Disputes, Remedies, and Re-shoots

Either principal may open a dispute on its own deal — the `Creator` or the `Brand`, matched by ownership — while the deal is `ACTIVE` or `COMPLETED`. The payload carries a `reason` (one of `RESHOOT_REQUEST`, `NON_PAYMENT`, `DISCLOSURE_VIOLATION`, `SCOPE_CREEP`, or `OTHER`), a free-text `note`, and a `deliverable_id` that is required when the reason is `RESHOOT_REQUEST` and optional otherwise. The dispute records which side spoke first in `raised_by_role`, as `CREATOR` or `BRAND`, and opens in `OPEN`. Raising a dispute on an `ACTIVE` deal moves the deal to `IN_DISPUTE`; on a `COMPLETED` deal the deal stays `COMPLETED`. Either way, every payout of the deal in `ACCRUED` or `PAYABLE` is held automatically.

A `BrandManager` then shepherds the dispute. Reviewing moves `OPEN` → `UNDER_REVIEW`. Resolution carries an `action` offering three values: `DISMISS`, which lands the dispute in `RESOLVED_DISMISSED`; `UPHOLD` with a `remedy`, which lands it in `RESOLVED_UPHELD`; and `ESCALATE`, which moves `UNDER_REVIEW` → `ESCALATED` while the case remains undecided. From `ESCALATED`, dismissal is still available, but an upheld resolution may apply only the two heaviest remedies, `TERMINATE` or `FEE_REDUCTION`. Every resolution records a `resolution_note`.

Dismissal, and upholding with one of the lighter remedies, returns an `IN_DISPUTE` deal to `ACTIVE` and unholds the payouts the dispute held — restoring each to `PAYABLE` when its `payout_due_at` is set and to `ACCRUED` otherwise. Three remedies attach consequences. `NONE` carries no further effect. `FEE_REDUCTION` copies the dispute's `reduction_pct` — a fraction strictly between zero and one, so 0.025 means a 2.5 percent cut, validated under the range rules of §2.8 — onto the deal's `reduction_pct`, and every later invoice prices its fee and service lines against the reduced fee. `RESHOOT` requires the dispute to reference a deliverable and creates a re-shoot in `REQUESTED` against it — refused with `ERR_RESHOOT_LIMIT_EXCEEDED` when that deliverable's `reshoot_count` has already reached the one-per-deliverable cap. The fourth remedy, `TERMINATE`, moves the deal from `IN_DISPUTE` to `TERMINATED` and runs the full termination cascade of §3.4 — deliverable cancellation, disclosure voiding with its pending-count recompute, invoice voiding with its balance compensation, payout clawback, and the brief's slot recompute.

Re-shoots also exist outside disputes: a `BrandManager` may request one directly on a deliverable in `APPROVED`, `PUBLISHED`, or `VERIFIED`, provided the deal sits in `ACTIVE` or `IN_DISPUTE` — requests against any other posture are rejected with `ERR_INVALID_STATE`. The request carries a `reason` and an optional `dispute_id`, which stays null for direct requests, and is refused with `ERR_RESHOOT_LIMIT_EXCEEDED` once the deliverable's `reshoot_count` has reached one. Either way the re-shoot opens in `REQUESTED` with `responded_at` null, and the answer belongs to the deal's creator, whose response carries an `action` of `ACCEPT` or `DECLINE`. Accepting moves the re-shoot to `ACCEPTED`, stamps `responded_at`, and resets the deliverable: it returns to `PENDING_SUBMISSION` from whichever of `APPROVED`, `PUBLISHED`, or `VERIFIED` it occupied, its `content_url`, `published_at`, and `verified_at` are cleared, its `reshoot_count` increments by one, its disclosure checks in `QUEUED` or `FAILED` are voided, and the creator's `pending_disclosure_count` is recomputed. Declining simply lands the re-shoot in `DECLINED` with `responded_at` stamped. `ACCEPTED` and `DECLINED` are terminal.

## 4. Endpoint Definitions

Operations that create a new resource — onboarding a creator or brand, creating a brief, pitch, deliverable, reshoot, dispute, performance report, or invoice — return `201 Created`. All other successful operations, including state transitions, respond actions, reviews, payments, and releases, return `200 OK`. List endpoints accept the pagination parameters of §2.3 plus optional filters scoped to the collection: `status`, `niche`, `min_followers`, `brand_id`, `brief_id`, `creator_id`, `deal_id`, `pitch_id`, `invoice_id`, `deliverable_id`, `dispute_id`, and `superseded_by_pitch_id`. Request payloads, preconditions, and side effects for each operation are specified by the workflows of §3; the table below is the addressing contract only.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/creators` | Onboard a creator (status `APPLIED`) | TalentManager |
| GET | `/creators` | List creators | TalentManager, BrandManager, FinanceAdmin, ComplianceOfficer |
| GET | `/creators/{id}` | Get one creator | TalentManager, BrandManager, FinanceAdmin, ComplianceOfficer, Creator |
| PATCH | `/creators/{id}/metrics` | Update audience metrics; recomputes the rate card | TalentManager |
| POST | `/creators/{id}/transition` | Advance, suspend, reinstate, or exit a creator | TalentManager |
| POST | `/brands` | Onboard a brand (status `ACTIVE`) | BrandManager |
| GET | `/brands` | List brands | BrandManager, FinanceAdmin, TalentManager |
| GET | `/brands/{id}` | Get one brand | BrandManager, FinanceAdmin, TalentManager, Brand |
| PATCH | `/brands/{id}` | Update brand attributes (status, credit hold) | BrandManager |
| POST | `/briefs` | Create a brief (`DRAFT`) | BrandManager |
| GET | `/briefs` | List briefs | BrandManager, TalentManager, Creator, Brand, FinanceAdmin |
| GET | `/briefs/{id}` | Get one brief | BrandManager, TalentManager, Creator, Brand, FinanceAdmin |
| POST | `/briefs/{id}/publish` | Publish a brief (`DRAFT` → `OPEN`) | BrandManager |
| POST | `/briefs/{id}/close` | Close a brief (`OPEN`/`AWARDED` → `CLOSED`) | BrandManager |
| GET | `/briefs/{id}/pitches` | List pitches of a brief | BrandManager, TalentManager |
| POST | `/briefs/{id}/pitches` | Create a pitch (OCC on brief version); supersedes the same creator's prior `SUBMITTED` pitch | TalentManager |
| GET | `/pitches` | List pitches with filters | BrandManager, TalentManager |
| GET | `/pitches/{id}` | Get one pitch | BrandManager, TalentManager |
| POST | `/pitches/{id}/brand-action` | Brand-side pitch action: `SHORTLIST`, `COUNTER`, `REJECT`, `ACCEPT` | BrandManager |
| POST | `/pitches/{id}/talent-action` | Talent-side pitch action: `RESUBMIT`, `WITHDRAW` | TalentManager |
| GET | `/deals` | List deals with filters | BrandManager, TalentManager, FinanceAdmin, Creator, Brand |
| GET | `/deals/{id}` | Get one deal | BrandManager, TalentManager, FinanceAdmin, Creator, Brand, ComplianceOfficer |
| POST | `/deals/{id}/propose-terms` | Propose deal terms (`DRAFT` → `PENDING_CREATOR`; OCC on deal version) | BrandManager |
| POST | `/deals/{id}/creator-respond` | Creator responds to terms: `ACCEPT`, `COUNTER`, `DECLINE` | Creator |
| POST | `/deals/{id}/brand-respond` | Brand responds to terms: `ACCEPT`, `COUNTER`, `DECLINE` | Brand |
| POST | `/deals/{id}/terminate` | Terminate an `ACTIVE` deal with full cascade | BrandManager |
| POST | `/deals/{id}/disputes` | Raise a dispute on an `ACTIVE` or `COMPLETED` deal | Creator, Brand |
| POST | `/deals/{id}/deliverables` | Plan a deliverable on an `ACTIVE` deal | BrandManager |
| GET | `/deals/{id}/deliverables` | List deliverables of a deal | BrandManager, TalentManager, Creator, Brand, ComplianceOfficer, FinanceAdmin |
| GET | `/deliverables/{id}` | Get one deliverable | BrandManager, TalentManager, Creator, Brand, ComplianceOfficer |
| POST | `/deliverables/{id}/submit` | Creator submits content for review | Creator |
| POST | `/deliverables/{id}/review` | Review a submission: `APPROVE` or `REQUEST_REVISION` | BrandManager |
| POST | `/deliverables/{id}/publish` | Creator marks content published | Creator |
| GET | `/deliverables/{id}/disclosure-checks` | List disclosure checks of a deliverable | ComplianceOfficer, BrandManager, Creator |
| GET | `/deliverables/{id}/reshoots` | List reshoots of a deliverable | BrandManager, Creator, TalentManager |
| POST | `/deliverables/{id}/reshoots` | Request a reshoot on an `APPROVED`/`PUBLISHED`/`VERIFIED` deliverable | BrandManager |
| POST | `/disclosure-checks/{id}/review` | Pass or fail a queued disclosure check | ComplianceOfficer |
| POST | `/disclosure-checks/{id}/requeue` | Creator requeues a `FAILED` check after fixing content | Creator |
| POST | `/deals/{id}/performance-reports` | Submit a performance report (OCC on deal version); supersedes overlapping `REPORTED` reports | BrandManager |
| GET | `/deals/{id}/performance-reports` | List performance reports of a deal | BrandManager, TalentManager, Creator, Brand, FinanceAdmin |
| POST | `/performance-reports/{id}/finalize` | Finalize a report with audited metrics | BrandManager |
| POST | `/deals/{id}/invoices` | Create an invoice (`DRAFT`) for a deal | FinanceAdmin |
| GET | `/invoices` | List invoices | FinanceAdmin, BrandManager, Brand |
| GET | `/invoices/{id}` | Get one invoice | FinanceAdmin, BrandManager, Brand |
| POST | `/invoices/{id}/issue` | Issue an invoice; sets the due date; creates an `ACCRUED` payout | FinanceAdmin |
| POST | `/invoices/{id}/record-payment` | Record brand payment; exact amount required | FinanceAdmin |
| POST | `/invoices/{id}/void` | Void a `DRAFT` or `ISSUED` invoice | FinanceAdmin |
| GET | `/payouts` | List payouts | FinanceAdmin, Creator, BrandManager |
| GET | `/payouts/{id}` | Get one payout | FinanceAdmin, Creator, BrandManager |
| POST | `/payouts/{id}/release` | Release a `PAYABLE` payout at or after its due instant | FinanceAdmin |
| POST | `/payouts/{id}/hold` | Hold an `ACCRUED` or `PAYABLE` payout | FinanceAdmin |
| POST | `/payouts/{id}/unhold` | Unhold a `HELD` payout, restoring `ACCRUED` or `PAYABLE` | FinanceAdmin |
| GET | `/disputes` | List disputes | BrandManager, Creator, Brand, FinanceAdmin |
| GET | `/disputes/{id}` | Get one dispute | BrandManager, Creator, Brand, FinanceAdmin |
| POST | `/disputes/{id}/review` | Move a dispute from `OPEN` to `UNDER_REVIEW` | BrandManager |
| POST | `/disputes/{id}/resolve` | Resolve a dispute: `DISMISS`, `UPHOLD` with a remedy, or `ESCALATE` | BrandManager |
| GET | `/reshoots` | List reshoots | BrandManager, Creator, TalentManager |
| GET | `/reshoots/{id}` | Get one reshoot | BrandManager, Creator, TalentManager |
| POST | `/reshoots/{id}/respond` | Creator accepts or declines a reshoot | Creator |
| POST | `/_clock/set_current_utc` | Set the logical clock; sweeps briefs and invoices | PlatformAdmin |

## 5. Error Code Catalogue

The catalogue below enumerates every machine-readable error identifier and its HTTP status. Trigger conditions for each error are specified in §2 and §3 alongside the workflow it guards.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_VALIDATION` | 400 Bad Request |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_ALREADY_TERMINAL` | 409 Conflict |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_SEGREGATION_OF_DUTIES` | 403 Forbidden |
| `ERR_CREATOR_COMPLIANCE_SUSPENDED` | 422 Unprocessable Entity |
| `ERR_DISCLOSURE_NOT_PASSED` | 409 Conflict |
| `ERR_EXCLUSIVITY_CONFLICT` | 409 Conflict |
| `ERR_PUBLISH_GAP_VIOLATION` | 409 Conflict |
| `ERR_DELIVERABLE_COUNT_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_REVISION_LIMIT_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_RESHOOT_LIMIT_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_NEGOTIATION_LIMIT_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_BRIEF_SLOTS_FULL` | 422 Unprocessable Entity |
| `ERR_PITCH_REQUIREMENTS_NOT_MET` | 422 Unprocessable Entity |
| `ERR_DUPLICATE_REPORT_PERIOD` | 422 Unprocessable Entity |
| `ERR_INVOICE_ALREADY_EXISTS` | 409 Conflict |
| `ERR_ACTIVE_DEALS_EXIST` | 422 Unprocessable Entity |
| `ERR_SUBMISSION_WINDOW_CLOSED` | 422 Unprocessable Entity |
| `ERR_PUBLISH_WINDOW_VIOLATION` | 422 Unprocessable Entity |
| `ERR_PAYOUT_NOT_DUE` | 422 Unprocessable Entity |
| `ERR_CREATOR_NOT_ACTIVE` | 422 Unprocessable Entity |
| `ERR_BRAND_SUSPENDED` | 422 Unprocessable Entity |
| `ERR_BRAND_CREDIT_HOLD` | 402 Payment Required |
| `ERR_BRIEF_BUDGET_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_PAYMENT_AMOUNT_MISMATCH` | 422 Unprocessable Entity |
