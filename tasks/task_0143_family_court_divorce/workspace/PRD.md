# Family Court Divorce Case Management API — Product Requirements Document

## 1. Introduction

A contested or uncontested divorce travels through a long, branching workflow before any party walks away with a final judgment: a petition is filed, the respondent is served and given a fixed window in which to answer, both spouses must produce sworn financial disclosures, custody and parenting arrangements have to be negotiated (and very often mediated), interim relief may be imposed by a temporary order, and only then can a court issue a final judgment that distributes property, fixes child support, and (when eligible) awards spousal support. This API is the system of record that drives that workflow end-to-end. It is consumed by attorneys, self-represented parties, mediators, and judges, and it must encode the procedural rules of family court — deadlines, segregation of duties, mediation caps, jurisdiction-specific support formulas, and property-division models — strictly enough that the same case file produces identical numeric outcomes regardless of operator.

The system favors deterministic, auditable behavior over flexible operator discretion. Every numeric calculation (child support, spousal support, asset division) is computed by the server from accepted disclosures rather than typed in by a clerk; every state change is driven by a small, named transition rather than by a generic update; and the logical clock that gates time-sensitive deadlines is operator-visible but only advances forward, so test scenarios and audits can be replayed exactly. Because family-law procedure varies by state, jurisdiction selection at petition time silently chooses both a child-support guideline (income-shares versus percentage-of-obligor) and a property-division model (community property versus equitable distribution); the implementer should treat the jurisdiction_state field as the routing key for all such variant calculations.

## 2. Global Specifications & System-Wide Principles

This section defines the cross-cutting contracts that every endpoint and every workflow in §3 inherits. The rules here are precise by design: response shape, pagination, common resource properties, rounding, optimistic concurrency, and the role/identity model. §3 builds on these without restating them.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID` identifies the acting user, and `X-User-Role` declares the operational capacity in which the request is being made. Missing or malformed headers cause the request to be rejected with `ERR_AUTH_MISSING` (HTTP 401). A request whose role is recognized but is not permitted for the targeted endpoint (per the §4 endpoint table) is rejected with `ERR_FORBIDDEN` (HTTP 403).

The system recognizes exactly six roles, spelled exactly as follows: `Petitioner`, `Respondent`, `AttorneyOfRecord`, `Judge`, `Mediator`, `PlatformAdmin`.

The identity model differs by role, and the implementer must respect this distinction in every authorization check:

- When `X-User-Role` is `Petitioner`, `X-User-ID` is the `id` of the acting `Party` row (specifically, the `Party` on the targeted case whose `role` is `PETITIONER`). Ownership checks on any resource that references a `Party` (for example, the `proposing_party_id` of a `ParentingPlan`, or the `party_id` of a `FinancialDisclosure`) compare the resource's party foreign-key field to `X-User-ID`.
- When `X-User-Role` is `Respondent`, `X-User-ID` is the `id` of the acting `Party` row (the `Party` on the targeted case whose `role` is `RESPONDENT`). Ownership checks are made the same way.
- When `X-User-Role` is `AttorneyOfRecord`, `X-User-ID` is an opaque attorney identifier; ownership is established by comparing `X-User-ID` to the `counsel_user_id` of the `Party` the attorney is acting on behalf of. The attorney may perform any operation that the represented party may perform, scoped to that party only, except for self-acceptance of a parenting plan their own party proposed (the same restriction that binds the party themselves).
- When `X-User-Role` is `Judge`, `X-User-ID` is an opaque judicial-officer identifier not tied to any persisted entity. Segregation of duties applies: a `Judge` may not also act as `Petitioner`, `Respondent`, `AttorneyOfRecord`, or `Mediator` on the same case.
- When `X-User-Role` is `Mediator`, `X-User-ID` is an opaque mediator identifier not tied to any persisted entity, although the server records it on each `MediationSession` it schedules via the session's `mediator_user_id` field. A `Mediator` may not also act as `Judge` on the same case.
- When `X-User-Role` is `PlatformAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; this role has no party-level operations.

Authorization is checked in priority order: header presence first (`ERR_AUTH_MISSING`), then role permission (`ERR_FORBIDDEN`), then path-resource existence (`ERR_NOT_FOUND`, validated left-to-right — see §2.4), and only then party-scoped ownership for `Petitioner`/`Respondent`/`AttorneyOfRecord` operations (also `ERR_FORBIDDEN`).

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

List endpoints are paginated via query parameters. The `limit` parameter specifies the maximum number of items returned; it defaults to 10, has a minimum of 1, and a maximum of 100. The `offset` parameter specifies how many items to skip and defaults to 0.

Unless an endpoint says otherwise, list responses are sorted by the resource's `created_at` field in ascending order.

The `meta` object on every list response carries the four pagination fields `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Nested Resource Resolution

Most endpoints in this API live below `/cases/{caseId}`, and many drill further (for example, the disclosures of a case live under `/cases/{caseId}/disclosures/{disclosureId}`, and the lifecycle endpoints on a single mediation session sit under `/cases/{caseId}/mediation-sessions/{sessionId}`). For every nested path the server validates the path identifiers strictly left to right: the `caseId` is resolved first, and only after the case is found does the server attempt to resolve the child identifier (such as `disclosureId`, `planId`, `sessionId`, `orderId`, `tempOrderId`, `judgmentId`, or `partyId`) within that case's scope. The first identifier in the path that does not name a real resource within its parent scope causes the request to fail with `ERR_NOT_FOUND` (HTTP 404); no later validation runs.

### 2.5. Common Resource Properties

The seven mutable, top-level domain entities — `Case`, `Party`, `FinancialDisclosure`, `ParentingPlan`, `SupportOrder`, `TemporaryOrder`, and `FinalJudgment` — share four system-managed properties:

- `id` — a server-minted UUID. Identifiers carry no type prefix.
- `created_at` — an ISO 8601 UTC timestamp with three fractional digits, set at creation and never mutated.
- `updated_at` — an ISO 8601 UTC timestamp with three fractional digits, refreshed on every mutation of the resource (including system-driven cascades described in §3, not only direct client edits).
- `version` — an integer that starts at 1 on creation and is incremented by 1 on every mutation of the resource. The increment is per-resource: if a single client call mutates two resources, both bump their own `version` independently.

Two entities are exceptions and do not carry the full set:

- `MediationSession` is treated as a lightweight log; it carries `id` and `created_at` but does not have `updated_at` or `version`.
- `ServerClock` is a singleton system entity exposing only the `now` field; it has neither `updated_at` nor `version`.

### 2.6. The Logical Clock

All time-sensitive logic in this system — the 30-day answer window, mediation session start windows, the no-show deadline, the marriage-duration calculation — reads "now" from a single logical server clock rather than from wall time. The clock is exposed as a `ServerClock` singleton whose only field is `now`. Operators may advance it by submitting a target instant in the `to_timestamp` field; the advance is monotone-only, meaning a request whose `to_timestamp` is earlier than the current `ServerClock.now` is rejected with `ERR_CLOCK_NOT_MONOTONE` (HTTP 409). The clock can be read by any authenticated role and is advanced only by `PlatformAdmin`.

### 2.7. Monetary Values and Precision

All monetary amounts in the system — incomes, deductions, premiums, childcare, assets, debts, and computed support and asset shares — are represented and stored as **integer cents**. The API surfaces them in fields whose names end in `_cents` (for example, `gross_monthly_income_cents`, `monthly_amount_cents`, `petitioner_asset_share_cents`). All intermediate arithmetic for the support and asset-division formulas is performed on integers; where a step calls for division or a percentage application, the formula's order of operations is pinned in §3.6 and §3.7 below so that the result is reproducible across implementations.

Where rounding is required, the system uses round-half-up to the nearest cent. For child support and spousal support, there is exactly one rounding step at the end of the formula; intermediate percentages and ratios are not pre-rounded to two decimals before being multiplied through. For asset division under equitable distribution, the result is produced by an integer-arithmetic recipe (multiply first, then integer-divide) and a residual-assignment rule that together guarantee the petitioner-share plus respondent-share is exactly equal to the net pool, with no drift.

### 2.8. Optimistic Concurrency Control

Any endpoint that targets a specific resource by identifier and changes that resource's state supports optimistic concurrency control via an optional `version` field in the request body. When supplied, the server compares the request's `version` to the current `version` on the targeted resource; on mismatch the request is rejected with `ERR_VERSION_CONFLICT` (HTTP 409). When the `version` field is omitted, the server processes the mutation without an OCC check. This applies notably to `PATCH /cases/{caseId}/disclosures/{disclosureId}` (which carries `version` plus any subset of the editable monetary fields) and to the lifecycle endpoints on disclosures, parenting plans, and support orders that also accept `version`.

### 2.9. Cascading Mutations and Hierarchical Status Reconciliation

Many client actions in this domain mutate more than one entity at a time, because the workflow itself is hierarchical. Three cascade patterns recur:

1. **Issuing a `TemporaryOrder` cascades to its `SupportOrder` children.** When a `Judge` issues a temporary order, the `TemporaryOrder` itself transitions from `DRAFT` to `EFFECTIVE` (its `effective_from` is set to now and the `Case.temporary_order_id` is set to its id), and every `TEMPORARY` `SupportOrder` referenced by that temporary order transitions from `DRAFT` to `ISSUED` (with `effective_from` set to now). The parent `Case.status` advances to `TEMP_ORDERED`.
2. **Issuing a `FinalJudgment` cascades to support orders and supersedes the temporary order.** When a `Judge` issues a final judgment, the `FinalJudgment` itself transitions from `DRAFT` to `EFFECTIVE` (its `effective_from` is set to now), every `FINAL` `SupportOrder` referenced by it transitions from `DRAFT` to `ISSUED`, and if `Case.temporary_order_id` is set, that `TemporaryOrder` transitions from `EFFECTIVE` to `SUPERSEDED` (its `superseded_at` is set to now) and every `TEMPORARY` `SupportOrder` it had referenced transitions to `SUPERSEDED` (with `superseded_by_id` pointing at the matching `FINAL` order of the same `support_type`). The parent `Case.status` advances to `FINALIZED` and `Case.final_judgment_id` is set.
3. **A `MediationSession` completion can cascade to a `ParentingPlan`.** When a `Mediator` completes a session with `outcome` set to `AGREEMENT` and supplies a `parenting_plan_id` belonging to the case, and both parties' disclosures are in `ACCEPTED`, the referenced `ParentingPlan` automatically transitions from `PROPOSED` or `COUNTERED` to `AGREED`, pinning both parties' disclosure versions. When `outcome` is `IMPASSE` and `Case.mediation_round` has reached 3, the latest `PROPOSED` or `COUNTERED` `ParentingPlan` is auto-transitioned to `CONTESTED`.

Every cascade follows the same accounting rule: each mutated resource independently bumps its own `version` and refreshes its own `updated_at`. A single client call therefore typically produces several resource-version increments — the implementer must not collapse them into one.

### 2.10. Concurrency and Serialization

Family-court workflows have a small set of high-stakes race conditions, and the system serializes each one with first-writer-wins semantics:

- **Answer versus Default on the same case.** If a `Respondent` files an answer at the same instant as a `Petitioner` requests default, the first writer wins the transition out of `AWAITING_ANSWER`. If default lands first, the answer attempt is rejected with `ERR_INVALID_STATE` (HTTP 409) because the case is no longer in `AWAITING_ANSWER`. If the answer lands first, the default attempt is also rejected with `ERR_INVALID_STATE` because `Respondent.has_filed_answer` is now true.
- **Two acceptances of the same parenting plan.** If both parties attempt to accept the same `ParentingPlan` simultaneously, exactly one accept succeeds; the second is rejected with `ERR_INVALID_STATE` (HTTP 409) because either the proposer-cannot-accept rule (§3.4) trips first or the plan is already `AGREED`.
- **Two completions of the same mediation session.** If two `Mediator` requests both try to mark the same `MediationSession` complete, exactly one wins; the loser sees the session already in a terminal state and is rejected with `ERR_INVALID_STATE` (HTTP 409).
- **A final judgment racing a counter parenting plan.** Issuing a final judgment requires `Case.status` to be `AWAITING_JUDGMENT`, while filing a counter parenting plan requires `Case.status` to be `MEDIATION`. Whichever request lands first defines the case status the second one sees; the loser is rejected with `ERR_INVALID_STATE` (HTTP 409).
- **A double-booked mediator.** If two scheduling requests against the same mediator's calendar produce a time overlap, the first writer wins and the second is rejected with `ERR_MEDIATOR_DOUBLE_BOOKED` (HTTP 409). Overlap is detected against any `SCHEDULED` or `IN_PROGRESS` session on the same `mediator_user_id` whose `[scheduled_start_at, scheduled_end_at)` interval intersects the proposed interval.

### 2.11. Validation Ordering

When a request fails several validation checks, the server returns the highest-priority failure. The fixed priority is: missing headers (`ERR_AUTH_MISSING`) first; then role permission (`ERR_FORBIDDEN`); then resource existence walked left-to-right along the path (`ERR_NOT_FOUND`); then party-scoped ownership (`ERR_FORBIDDEN`); then state-transition legality (`ERR_INVALID_STATE`); then the cross-entity disclosure-completeness check (`ERR_DISCLOSURE_INCOMPLETE`); then time-window and schedule-overlap checks (`ERR_ANSWER_WINDOW_EXPIRED`, `ERR_MEDIATOR_DOUBLE_BOOKED`); then business-constraint checks such as proposer/acceptor identity and overnight totals; then domain-fiscal checks (spousal eligibility, disclosure internal consistency); then the mediation-cap and mediation-exhaustion checks; then the mediation start-window check; then the temporary-order field-combination check; then the separation-after-marriage check; and finally the OCC `version` check (`ERR_VERSION_CONFLICT`). The implementer must respect this ordering: surfacing a lower-priority error when a higher-priority one also applies is itself a defect.

## 3. Business Logic & Workflows

The seven subsections below trace the lifecycle of a divorce case from the moment a petition is filed to the moment a final judgment becomes effective. Field names, formulas, and rule thresholds are deliberately introduced in the subsection where they make business sense — implementers should expect, for example, that the `override` semantics for `obligee_remarried` show up in the support-termination narrative rather than in the support-creation narrative.

### 3.1. Petition Filing and the Answer Window

A `Petitioner` (or an `AttorneyOfRecord` acting on their behalf) initiates a case by filing a petition. The request body carries `jurisdiction_state` (which must be one of `CA`, `NY`, `TX`, `FL`, `IL`, or `WA`), `marriage_date`, `separation_date`, `has_minor_children`, and two nested party records — one `petitioner` and one `respondent` — each carrying `full_name`, `date_of_birth`, `gross_monthly_income_cents` (a self-reported W-2 monthly gross figure used only until the formal `FinancialDisclosure` is accepted), and an optional `counsel_user_id` for an attorney of record.

The server validates that `separation_date` is strictly later than `marriage_date`; if not, it rejects with `ERR_SEPARATION_BEFORE_MARRIAGE` (HTTP 422). On acceptance, the server mints a `Case` row in initial status `FILED`, mints two `Party` rows (one with `role` `PETITIONER` and one with `role` `RESPONDENT`), records the petitioner's `Party.id` on the case as `petitioner_party_id` and the respondent's `Party.id` as `respondent_party_id`, and stamps `Party.served_at = now()` on the respondent's row (the petitioner's `served_at` remains null). The `Party.has_filed_answer` flag is initialized to `false` on both rows. The server also mints `Case.docket_number` in the format `FC-YYYY-NNNNNN`. The system then immediately advances `Case.status` from `FILED` to `AWAITING_ANSWER` and pins `Case.answer_deadline_at` to exactly thirty days after the case's `created_at` timestamp. That deadline is set once at petition acceptance and is not affected by when the respondent is served.

While the case is in `AWAITING_ANSWER`, two outcomes are possible. The `Respondent` (or their `AttorneyOfRecord`) can file an answer, provided now is at or before `Case.answer_deadline_at` and `Respondent.has_filed_answer` is currently false. If now is past the deadline, the answer attempt is rejected with `ERR_ANSWER_WINDOW_EXPIRED` (HTTP 409). On a successful answer the server sets `Respondent.has_filed_answer` to true, sets `Case.response_received_at = now()`, and transitions `Case.status` from `AWAITING_ANSWER` to `ANSWERED`. The alternative outcome — chosen by the `Petitioner` (or their attorney) once the window has closed — is to request entry of default; this is only allowed when now is strictly after `Case.answer_deadline_at` and the respondent has not filed an answer. Requesting default while the window is still open is rejected with `ERR_ANSWER_WINDOW_OPEN` (HTTP 409). On a successful default request the case transitions from `AWAITING_ANSWER` to `DEFAULTED`. The default path bypasses the mediation requirement that applies on the answered path; specifically, a `DEFAULTED` case advances directly toward `AWAITING_JUDGMENT` once the petitioner's `FinancialDisclosure` is accepted.

A `Judge` may also dismiss the case while it is in `FILED` or `AWAITING_ANSWER`, supplying a free-text `reason`; the case transitions to `DISMISSED` and the workflow terminates there.

### 3.2. Financial Disclosures: Draft, Submit, Accept, Reject

After the case has been answered (or even before, in the rare race), each `Party` is expected to file their own `FinancialDisclosure`. A `Petitioner`, `Respondent`, or `AttorneyOfRecord` creates the disclosure in `DRAFT` status, supplying the party's `party_id`, `gross_monthly_income_cents` (the verified gross figure that supersedes the petition-time number for all calculations), `deductible_taxes_cents` (monthly tax plus payroll deductions), `monthly_health_insurance_cents` (health insurance premium attributable to the children), `monthly_childcare_cents` (work-related childcare cost), `assets_total_cents`, and `debts_total_cents`. The pair `(case_id, party_id)` is unique on the case — a second create attempt for the same party is rejected with `ERR_DUPLICATE_DISCLOSURE` (HTTP 409). The server computes `net_monthly_income_cents` immediately as the gross income minus the deductible taxes, floored at zero so it is never negative; this derived field is recomputed on every submit and every accept.

Owning parties may edit a `DRAFT` or `REJECTED` disclosure, sending the current `version` for OCC together with any subset of the six monetary fields above. On submit, the system enforces that every numeric field is non-negative, that `gross_monthly_income_cents` is strictly greater than zero (otherwise `ERR_DISCLOSURE_INCOMPLETE`, HTTP 409), and that `deductible_taxes_cents` does not exceed `gross_monthly_income_cents` (otherwise `ERR_DISCLOSURE_INCONSISTENT`, HTTP 422). On a successful submit, the disclosure moves from `DRAFT` to `SUBMITTED`, `net_monthly_income_cents` is recomputed, and if `Case.status` was `ANSWERED` it advances to `DISCLOSURE`; if `Case.status` was `DEFAULTED` it remains `DEFAULTED` but the disclosure progress is tracked.

A `Judge` reviews each submitted disclosure. Accepting it transitions the disclosure from `SUBMITTED` to `ACCEPTED`; if the case is in `DEFAULTED` and the accepted disclosure belongs to the petitioner, the case additionally cascades from `DEFAULTED` to `AWAITING_JUDGMENT`. Rejecting it requires a `rejection_reason` in the request body — submitting a rejection without one is refused with `ERR_REJECTION_REASON_REQUIRED` (HTTP 422). On rejection the disclosure transitions from `SUBMITTED` to `REJECTED` and the reason is stored. The owning party can then patch the disclosure (correcting any of the six monetary fields) which returns it from `REJECTED` to `DRAFT` and clears `rejection_reason` back to null. Acceptance is terminal: once a disclosure is `ACCEPTED`, it stays there.

### 3.3. Parenting Plans, Counters, Self-Accept, and Overnight Totals

Cases involving minor children (`has_minor_children` true) require a `ParentingPlan` to be in place before any temporary or final order can issue. A `Petitioner`, `Respondent`, or `AttorneyOfRecord` proposes a plan by supplying the `proposing_party_id` (which must match the acting party), the `legal_custody` choice (one of `JOINT`, `PETITIONER_SOLE`, or `RESPONDENT_SOLE`), the `physical_custody` choice (one of `JOINT`, `PETITIONER_PRIMARY`, or `RESPONDENT_PRIMARY`), and the two overnight counts `petitioner_overnights_per_year` and `respondent_overnights_per_year`. Each overnight count must be in the inclusive range zero to 365, and the two values must sum to exactly 365; any other combination is rejected with `ERR_OVERNIGHTS_INVALID` (HTTP 422). A freshly proposed plan starts in `PROPOSED`.

A plan can be **countered** by the other party by submitting a new plan whose body includes `countered_plan_id` pointing back at the plan being countered. The counter must be filed by the party who did **not** propose the original; an attempt by the original proposer (or their attorney) to file the counter is rejected with `ERR_COUNTER_BY_PROPOSER` (HTTP 422). On a successful counter the original plan transitions from `PROPOSED` to `COUNTERED` and its `countered_by_plan_id` is set to the id of the new plan.

A plan in either `PROPOSED` or `COUNTERED` is accepted by the non-proposing party. The acceptor must not be the proposer (otherwise `ERR_SELF_ACCEPT`, HTTP 422), no newer counter may exist on the plan being accepted (its `countered_by_plan_id` must still be null), and both parties' disclosures must already be in `ACCEPTED` (otherwise `ERR_DISCLOSURE_INCOMPLETE`, HTTP 409). On a successful accept the plan transitions to `AGREED`, and the server pins `pinned_petitioner_disclosure_version` and `pinned_respondent_disclosure_version` to the current `version` of each party's accepted disclosure — this snapshot is what binds the parenting agreement to a specific income picture and is what later support calculations reconcile against.

The system also produces parenting plans through the mediation and court-imposition paths described in §3.4. Once a `FinalJudgment` with a different `parenting_plan_id` becomes `EFFECTIVE`, any other `AGREED` or `COURT_IMPOSED` plan on the case transitions to `SUPERSEDED`.

### 3.4. Mediation: Scheduling, the Three-Round Cap, and Outcomes

Once both parties have `ACCEPTED` disclosures and the case has at least one parenting plan in `PROPOSED`, `COUNTERED`, or `AGREED`, the `Petitioner` (or their attorney) can move the case into mediation. This is only available on the answered path: a case that reached `DISCLOSURE` via the `DEFAULTED` branch does not run mediation. The system also blocks the transition if either disclosure is not yet `ACCEPTED` (`ERR_DISCLOSURE_INCOMPLETE`). On success the case transitions from `DISCLOSURE` to `MEDIATION` and `Case.mediation_round` (which started at zero on case creation) is now eligible to count its first session.

Scheduling a session is done by a `Mediator` or `Judge` by supplying `mediator_user_id`, `scheduled_start_at`, and `scheduled_end_at`. The session length, computed as end minus start, must be exactly 60, 120, or 180 minutes; `scheduled_end_at` must be strictly after `scheduled_start_at`. The scheduler must not overlap any other `SCHEDULED` or `IN_PROGRESS` session on the same `mediator_user_id`; overlap is checked against the half-open interval `[scheduled_start_at, scheduled_end_at)` and on conflict the request is rejected with `ERR_MEDIATOR_DOUBLE_BOOKED` (HTTP 409). The system also enforces a hard ceiling of three mediation rounds: when `Case.mediation_round` has already reached 3, a fourth scheduling attempt is rejected with `ERR_MEDIATION_CAP_REACHED` (HTTP 409), unless the immediately previous session was `CANCELLED` (cancelled sessions do not count toward the cap, although `COMPLETED` and `NO_SHOW` sessions do). The session's `round_index` is set to the value of `Case.mediation_round` plus one at scheduling time, so the first session's `round_index` is 1.

A `Mediator` starts a session by marking it `IN_PROGRESS`; this is only permitted when now is at or after `scheduled_start_at - 15 minutes` and at or before `scheduled_end_at`. Outside that window the start request is rejected with `ERR_SESSION_OUT_OF_WINDOW` (HTTP 409). Completion requires an `outcome` in the request (`AGREEMENT`, `PARTIAL`, or `IMPASSE`); missing `outcome` is rejected with `ERR_OUTCOME_REQUIRED` (HTTP 422). When `outcome` is `AGREEMENT` or `PARTIAL`, the request must also carry a `parenting_plan_id` referring to a plan that belongs to the case. On completion the session transitions from `IN_PROGRESS` to `COMPLETED` and `Case.mediation_round` is incremented by one. If the outcome is `AGREEMENT`, a `parenting_plan_id` is supplied, and both parties' disclosures are `ACCEPTED`, the referenced plan auto-transitions from `PROPOSED` or `COUNTERED` to `AGREED` (with the same disclosure-version pinning rule as a direct accept); if disclosures are not yet `ACCEPTED`, the session still completes with `outcome = AGREEMENT` but the plan stays in its current status. If the outcome is `IMPASSE` and `Case.mediation_round` has now reached 3, the latest active plan in `PROPOSED` or `COUNTERED` transitions to `CONTESTED`.

A session can also be cancelled before it starts (rejected with `ERR_SESSION_ALREADY_STARTED`, HTTP 409, if now is at or after `scheduled_start_at`) — cancellation does not increment `Case.mediation_round`. Alternatively, a session may be marked `NO_SHOW` after `scheduled_end_at` has passed; a no-show request submitted earlier is rejected with `ERR_SESSION_NOT_OVER` (HTTP 409). A `NO_SHOW` session, like a `COMPLETED` one, increments `Case.mediation_round` by one and counts toward the three-round cap.

When the cap has been hit and the parties still disagree, a `CONTESTED` plan may be court-imposed by a `Judge`; the request requires the plan to be in `CONTESTED` status and `Case.mediation_round` to be at least 3 (otherwise `ERR_MEDIATION_NOT_EXHAUSTED`, HTTP 409). On success the plan transitions to `COURT_IMPOSED`. The case advances from `MEDIATION` to `AWAITING_JUDGMENT` when either the latest plan is `AGREED` or, with `Case.mediation_round` at or above 3, a plan exists in `COURT_IMPOSED`.

### 3.5. Support Orders and Jurisdiction-Driven Guidelines

A `SupportOrder` is created by a `Judge` via a request carrying `support_type` (either `CHILD` or `SPOUSAL`), `order_kind` (either `TEMPORARY` or `FINAL`), and — only for `CHILD` orders — `parenting_plan_id`. The system rejects with `ERR_PLAN_REQUIRED_OR_FORBIDDEN` (HTTP 422) any `CHILD` request that omits `parenting_plan_id` or any `SPOUSAL` request that includes one. The server itself sets `obligor_party_id` and `obligee_party_id` based on the guideline calculation (whichever party has the higher computed obligation pays the other) and computes `monthly_amount_cents` at creation; the order is minted in `DRAFT`.

#### Child support — two variant guidelines

The child-support formula reads each party's most recently `ACCEPTED` `FinancialDisclosure` and the parenting plan referenced in the request. Let P_net be the petitioner's `net_monthly_income_cents` and R_net the respondent's, and let combined be their sum. From the parenting plan, let P_overnights be `petitioner_overnights_per_year` and R_overnights be `respondent_overnights_per_year`.

The first step is to compute a **basic support** figure from combined income, using a four-tier piecewise schedule. When combined is at or below 200,000 cents (the first tier ceiling), basic is combined multiplied by 0.17, rounded to a whole number of cents. When combined is above 200,000 but at or below 500,000 cents (the second tier ceiling), basic is 200,000 multiplied by 0.17 plus the excess of combined over 200,000 multiplied by 0.20, again rounded to a whole number of cents. When combined is above 500,000 but at or below 1,000,000 cents (the third tier ceiling), basic is 200,000 multiplied by 0.17 plus 300,000 multiplied by 0.20 plus the excess of combined over 500,000 multiplied by 0.22. When combined exceeds 1,000,000 cents, basic is 200,000 multiplied by 0.17 plus 300,000 multiplied by 0.20 plus 500,000 multiplied by 0.22 plus the excess of combined over 1,000,000 multiplied by 0.10.

Next, the system adds **presumed add-ons** equal to the sum of both parties' `monthly_childcare_cents` plus both parties' `monthly_health_insurance_cents`. Call this sum addons, and let total_basic equal basic plus addons.

Apportionment then depends on the case's `jurisdiction_state`:

- When `jurisdiction_state` is `CA`, `NY`, or `IL`, the system uses the **income-shares** model, and `SupportOrder.guideline_model` is recorded as `INCOME_SHARES`. The obligor is whichever party has the higher (or equal) `net_monthly_income_cents`; ties go to the respondent. The obligor's income share is the obligor's net divided by combined, and the obligor's overnight share is the obligor's overnight count divided by 365. The monthly support amount, before rounding, equals total_basic multiplied by the difference of the obligor's income share minus one-half of the obligor's overnight share. The implementer must perform exactly one round-half-up step at the very end, on the final amount in cents — the income share and overnight share are not pre-rounded to two decimals before being multiplied through. If the resulting `monthly_amount_cents` would be negative, it is clamped to zero.
- When `jurisdiction_state` is `TX`, `FL`, or `WA`, the system uses the **percent-of-obligor** model, and `guideline_model` is recorded as `PERCENT_OBLIGOR`. The obligor is again the party with the higher (or equal) net income, and let obligor_net denote the obligor's `net_monthly_income_cents`. This model tiers on the obligor's net alone, ignoring the other party's income: when obligor_net is at or below 200,000 cents the rate is 0.20; above 200,000 and at or below 500,000 the rate is 0.22; above 500,000 and at or below 1,000,000 the rate is 0.25; above 1,000,000 the rate is 0.27. The monthly amount equals obligor_net multiplied by that rate, rounded to a whole number of cents, plus the addons total multiplied by the ratio of obligor_net to combined (or zero if combined is zero), rounded to a whole number of cents. The two rounded pieces are added to produce `monthly_amount_cents`; overnight counts are not used in this variant.

#### Spousal support — eligibility and tiered transfer

Spousal support is gated on marriage duration. The server computes `marriage_duration_years` as the floor of the number of days between `Case.marriage_date` and `Case.separation_date` divided by 365.25 — so a marriage that lasted four years and 364 days yields `marriage_duration_years` of 4 and is ineligible. When `marriage_duration_years` is less than 5, attempting to create a `SPOUSAL` support order is rejected with `ERR_NOT_ELIGIBLE_FOR_SPOUSAL` (HTTP 422).

When eligible, the formula reads each party's most recently `ACCEPTED` `FinancialDisclosure`. Let higher be the larger of P_net and R_net and lower be the smaller; let gap equal higher minus lower. The transfer percentage tiers on duration: when `marriage_duration_years` is at least 5 and less than 10, the percentage is 0.30; at least 10 and less than 20, the percentage is 0.35; at or above 20, the percentage is 0.40. The pre-cap monthly amount is gap multiplied by the percentage, rounded half-up to a whole number of cents. A statutory cap then applies: the monthly amount may not exceed higher multiplied by 0.40, rounded half-up. If the pre-cap amount is above the cap, the amount is reduced to the cap. The resulting figure is stored as `monthly_amount_cents`. The guideline_model field is not used for spousal orders.

#### Termination of an issued support order

An `ISSUED` `SupportOrder` may be terminated by a `Judge`. For a `CHILD` order, termination is permitted when no child on the case is currently under 18. For a `SPOUSAL` order, termination is permitted when the request body's `obligee_remarried` flag is true. On success the order transitions from `ISSUED` to `TERMINATED`. Separately, an `ISSUED` order is auto-superseded by the system whenever a newer `SupportOrder` of the same `support_type` on the same case becomes `ISSUED`: the older order transitions to `SUPERSEDED` and its `superseded_by_id` is set to the new order's id.

### 3.6. Temporary and Final Orders

A **temporary order** is the interim package a `Judge` puts in place while the case heads toward final judgment. The judge first creates a `TemporaryOrder` in `DRAFT` by referencing the relevant existing draft sub-resources: when `Case.has_minor_children` is true, the body must carry both `parenting_plan_id` and `child_support_order_id`, and may optionally carry `spousal_support_order_id`; when `Case.has_minor_children` is false, both `parenting_plan_id` and `child_support_order_id` must be null, and only `spousal_support_order_id` (if any) is supplied. Any other combination of these three fields is rejected with `ERR_TEMP_ORDER_FIELDS` (HTTP 422).

The judge then issues the temporary order. The transition requires the temporary order to be in `DRAFT`, both disclosures to be `ACCEPTED`, and — when there are minor children — at least one parenting plan in `PROPOSED`, `COUNTERED`, or `AGREED` when the case is in `DISCLOSURE`, or in `AGREED`, `CONTESTED`, or `COURT_IMPOSED` when the case is in `MEDIATION`. On success the cascade in §2.9 fires: the `TemporaryOrder` advances to `EFFECTIVE`, `effective_from` is set to now, every referenced `TEMPORARY` `SupportOrder` advances from `DRAFT` to `ISSUED`, `Case.temporary_order_id` is set, and `Case.status` becomes `TEMP_ORDERED`. The case then progresses to `AWAITING_JUDGMENT` automatically, either as soon as a parenting plan is `AGREED` or `COURT_IMPOSED` (when `has_minor_children` is true) or directly (when `has_minor_children` is false).

A **final judgment** is the closing instrument. A `Judge` creates a `FinalJudgment` in `DRAFT`, with the same field-combination rules on `parenting_plan_id`, `child_support_order_id`, and `spousal_support_order_id` as the temporary order (governed by `has_minor_children`). The referenced `parenting_plan_id` must be a plan in `AGREED` or `COURT_IMPOSED` status. On `DRAFT` creation the server computes `petitioner_asset_share_cents` and `respondent_asset_share_cents` and records `division_model` (these are read-only after `EFFECTIVE`).

The judge then issues the final judgment. The transition requires the judgment to be in `DRAFT` on this case, both disclosures to be `ACCEPTED`, and — when there are minor children — the referenced `parenting_plan_id` to be `AGREED` or `COURT_IMPOSED`. On success the §2.9 cascade fires: `FinalJudgment` advances to `EFFECTIVE` with `effective_from` set to now, every referenced `FINAL` `SupportOrder` advances from `DRAFT` to `ISSUED`, any existing `Case.temporary_order_id` `TemporaryOrder` transitions from `EFFECTIVE` to `SUPERSEDED` with `superseded_at` set to now (and its `TEMPORARY` `SupportOrders` are likewise marked `SUPERSEDED`), `Case.final_judgment_id` is set, and `Case.status` becomes `FINALIZED`.

#### Asset division — two variant models

The asset-division calculation runs on each party's most recently `ACCEPTED` `FinancialDisclosure`. Let P_assets be the petitioner's `assets_total_cents`, R_assets be the respondent's, P_debts be the petitioner's `debts_total_cents`, and R_debts be the respondent's. The gross pool is P_assets plus R_assets; the net pool is the gross pool minus P_debts minus R_debts. Note that net pool can be negative, in which case the system still apportions it (parties share the marital debt).

- When `jurisdiction_state` is `CA`, `TX`, or `WA`, the system uses the **community-property** model and records `division_model` as `COMMUNITY_PROPERTY`. The net pool is split 50/50: the petitioner gets the integer-division half plus any odd-cent residual, and the respondent gets the plain integer-division half. Concretely, the petitioner's share equals the floor of net pool divided by 2, plus the difference between net pool and twice that floor; the respondent's share equals the floor of net pool divided by 2. The petitioner-plus-respondent invariant therefore holds exactly with no drift.
- When `jurisdiction_state` is `NY`, `FL`, or `IL`, the system uses the **equitable-distribution** model and records `division_model` as `EQUITABLE_DISTRIBUTION`. Shares are weighted toward the lower earner: the petitioner's share is computed in integer arithmetic by multiplying the net pool by the respondent's `net_monthly_income_cents` first and only then integer-dividing by the sum of the two parties' `net_monthly_income_cents` (this multiply-first-then-divide order is pinned to prevent float drift); the respondent's share is the net pool minus the petitioner's share, which preserves the no-drift invariant. As a degenerate case, when the two parties' net monthly incomes sum to zero, the petitioner's share is the integer-division half of the net pool, and the respondent's share is again net pool minus that, so the invariant still holds.

In both models, the resulting `petitioner_asset_share_cents` plus `respondent_asset_share_cents` equals the net pool exactly.

### 3.7. The Read Surface and the Logical Clock in Operation

Throughout the lifecycle the system exposes read endpoints for every entity — case detail, case lists (filterable by `status` and `jurisdiction_state` for `Judge` and `PlatformAdmin`), party detail and lists, disclosure lists, parenting-plan detail and lists, mediation-session lists, support-order detail and lists, temporary-order detail, and final-judgment detail. The list endpoints honor the `limit` and `offset` query parameters and the `created_at` ascending sort described in §2.3.

Time advances through the test-driving `_clock` capability described in §2.6. Because the answer window, the mediation start window, the no-show deadline, and the marriage-duration calculation all derive from `ServerClock.now`, an operator running a scenario from petition to final judgment generally interleaves clock advances with case actions: advance the clock to the day after `answer_deadline_at` before requesting default, advance to between `scheduled_start_at - 15 minutes` and `scheduled_end_at` before starting a mediation session, and advance past `scheduled_end_at` before marking the session as no-show. Reading the clock is permitted for every authenticated role; advancing it remains a `PlatformAdmin`-only capability.

## 4. Endpoint Definitions

Endpoint requests that create new, addressable resources (a new `Case`, a new `FinancialDisclosure`, a new `ParentingPlan`, a new `MediationSession`, a new `SupportOrder`, a new `TemporaryOrder`, or a new `FinalJudgment`) return `201 Created`. All other successful endpoints — state-transition actions, lifecycle endpoints, the clock endpoints, and every list/detail read — return `200 OK`. Request bodies, computed side effects, and detailed response shapes are not enumerated here; they are described in the relevant §3 subsection.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST   | `/_clock/advance`                                                | Advance the logical server clock to a supplied instant.                       | PlatformAdmin |
| GET    | `/_clock`                                                        | Read the current logical server clock.                                        | PlatformAdmin, Petitioner, Respondent, Judge, Mediator, AttorneyOfRecord |
| POST   | `/cases`                                                         | File a petition; mint Petitioner and Respondent Party rows.                   | AttorneyOfRecord, Petitioner |
| GET    | `/cases/{caseId}`                                                | Get case detail.                                                              | Petitioner, Respondent, Judge, AttorneyOfRecord, PlatformAdmin |
| GET    | `/cases`                                                         | List cases (filter by `status`, `jurisdiction_state`).                        | Judge, PlatformAdmin |
| POST   | `/cases/{caseId}/answer`                                         | Respondent files Answer.                                                      | Respondent, AttorneyOfRecord |
| POST   | `/cases/{caseId}/default`                                        | Petitioner requests entry of default after the answer window expires.         | Petitioner, AttorneyOfRecord |
| POST   | `/cases/{caseId}/start-mediation`                                | Petitioner moves the case from disclosure into mediation.                     | Petitioner, AttorneyOfRecord |
| POST   | `/cases/{caseId}/issue-temp-order`                               | Judge issues the referenced draft TemporaryOrder.                             | Judge |
| POST   | `/cases/{caseId}/issue-final-judgment`                           | Judge issues the referenced draft FinalJudgment.                              | Judge |
| POST   | `/cases/{caseId}/dismiss`                                        | Judge dismisses the case (with a reason) before answer.                       | Judge |
| GET    | `/cases/{caseId}/parties`                                        | List parties on the case.                                                     | Petitioner, Respondent, Judge, AttorneyOfRecord, PlatformAdmin |
| GET    | `/cases/{caseId}/parties/{partyId}`                              | Get a party.                                                                  | Petitioner, Respondent, Judge, AttorneyOfRecord, PlatformAdmin |
| POST   | `/cases/{caseId}/disclosures`                                    | Create a FinancialDisclosure in DRAFT for the acting party.                   | Petitioner, Respondent, AttorneyOfRecord |
| PATCH  | `/cases/{caseId}/disclosures/{disclosureId}`                     | Update a DRAFT or REJECTED disclosure (uses `version` OCC).                   | Petitioner, Respondent, AttorneyOfRecord |
| POST   | `/cases/{caseId}/disclosures/{disclosureId}/submit`              | Owning party submits a disclosure for review.                                 | Petitioner, Respondent, AttorneyOfRecord |
| POST   | `/cases/{caseId}/disclosures/{disclosureId}/accept`              | Judge accepts a submitted disclosure.                                         | Judge |
| POST   | `/cases/{caseId}/disclosures/{disclosureId}/reject`              | Judge rejects a submitted disclosure (with a reason).                         | Judge |
| GET    | `/cases/{caseId}/disclosures`                                    | List disclosures on the case.                                                 | Petitioner, Respondent, Judge, AttorneyOfRecord |
| POST   | `/cases/{caseId}/parenting-plans`                                | Propose a ParentingPlan, or counter an existing one.                          | Petitioner, Respondent, AttorneyOfRecord |
| POST   | `/cases/{caseId}/parenting-plans/{planId}/accept`                | Non-proposing party accepts a plan.                                           | Petitioner, Respondent, AttorneyOfRecord |
| POST   | `/cases/{caseId}/parenting-plans/{planId}/impose`                | Judge court-imposes a contested plan once the mediation cap is reached.       | Judge |
| GET    | `/cases/{caseId}/parenting-plans`                                | List parenting plans on the case.                                             | Petitioner, Respondent, Judge, AttorneyOfRecord |
| GET    | `/cases/{caseId}/parenting-plans/{planId}`                       | Get a parenting plan.                                                         | Petitioner, Respondent, Judge, AttorneyOfRecord |
| POST   | `/cases/{caseId}/mediation-sessions`                             | Schedule a mediation session.                                                 | Mediator, Judge |
| POST   | `/cases/{caseId}/mediation-sessions/{sessionId}/start`           | Mediator marks a scheduled session in progress.                               | Mediator |
| POST   | `/cases/{caseId}/mediation-sessions/{sessionId}/complete`        | Mediator completes a session with an outcome.                                 | Mediator |
| POST   | `/cases/{caseId}/mediation-sessions/{sessionId}/cancel`          | Cancel a session before it starts.                                            | Mediator, Judge |
| POST   | `/cases/{caseId}/mediation-sessions/{sessionId}/no-show`         | Mark a scheduled session as no-show after its end time.                       | Mediator, Judge |
| GET    | `/cases/{caseId}/mediation-sessions`                             | List mediation sessions for the case.                                         | Petitioner, Respondent, Judge, Mediator, AttorneyOfRecord |
| POST   | `/cases/{caseId}/support-orders`                                 | Create a DRAFT SupportOrder; server computes `monthly_amount_cents`.          | Judge |
| GET    | `/cases/{caseId}/support-orders/{orderId}`                       | Get a support order.                                                          | Petitioner, Respondent, Judge, AttorneyOfRecord |
| POST   | `/cases/{caseId}/support-orders/{orderId}/terminate`             | Terminate an ISSUED support order (e.g., child reaches 18 or obligee remarried). | Judge |
| GET    | `/cases/{caseId}/support-orders`                                 | List support orders on the case.                                              | Petitioner, Respondent, Judge, AttorneyOfRecord |
| POST   | `/cases/{caseId}/temp-orders`                                    | Create a DRAFT TemporaryOrder bundling support and parenting references.      | Judge |
| GET    | `/cases/{caseId}/temp-orders/{tempOrderId}`                      | Get a temporary order.                                                        | Petitioner, Respondent, Judge, AttorneyOfRecord |
| POST   | `/cases/{caseId}/final-judgments`                                | Create a DRAFT FinalJudgment; server computes asset shares.                   | Judge |
| GET    | `/cases/{caseId}/final-judgments/{judgmentId}`                   | Get a final judgment.                                                         | Petitioner, Respondent, Judge, AttorneyOfRecord |

## 5. Error Code Catalogue

| Error ID                          | HTTP Status Code |
| --------------------------------- | ---------------- |
| `ERR_AUTH_MISSING`                | 401 Unauthorized |
| `ERR_FORBIDDEN`                   | 403 Forbidden    |
| `ERR_NOT_FOUND`                   | 404 Not Found    |
| `ERR_INVALID_STATE`               | 409 Conflict     |
| `ERR_VERSION_CONFLICT`            | 409 Conflict     |
| `ERR_DISCLOSURE_INCOMPLETE`       | 409 Conflict     |
| `ERR_DISCLOSURE_INCONSISTENT`     | 422 Unprocessable Entity |
| `ERR_DUPLICATE_DISCLOSURE`        | 409 Conflict     |
| `ERR_REJECTION_REASON_REQUIRED`   | 422 Unprocessable Entity |
| `ERR_ANSWER_WINDOW_EXPIRED`       | 409 Conflict     |
| `ERR_ANSWER_WINDOW_OPEN`          | 409 Conflict     |
| `ERR_COUNTER_BY_PROPOSER`         | 422 Unprocessable Entity |
| `ERR_SELF_ACCEPT`                 | 422 Unprocessable Entity |
| `ERR_OVERNIGHTS_INVALID`          | 422 Unprocessable Entity |
| `ERR_PLAN_REQUIRED_OR_FORBIDDEN`  | 422 Unprocessable Entity |
| `ERR_NOT_ELIGIBLE_FOR_SPOUSAL`    | 422 Unprocessable Entity |
| `ERR_MEDIATION_CAP_REACHED`       | 409 Conflict     |
| `ERR_MEDIATION_NOT_EXHAUSTED`     | 409 Conflict     |
| `ERR_MEDIATOR_DOUBLE_BOOKED`      | 409 Conflict     |
| `ERR_SESSION_OUT_OF_WINDOW`       | 409 Conflict     |
| `ERR_SESSION_NOT_OVER`            | 409 Conflict     |
| `ERR_SESSION_ALREADY_STARTED`     | 409 Conflict     |
| `ERR_OUTCOME_REQUIRED`            | 422 Unprocessable Entity |
| `ERR_TEMP_ORDER_FIELDS`           | 422 Unprocessable Entity |
| `ERR_SEPARATION_BEFORE_MARRIAGE`  | 422 Unprocessable Entity |
| `ERR_CLOCK_NOT_MONOTONE`          | 409 Conflict     |
