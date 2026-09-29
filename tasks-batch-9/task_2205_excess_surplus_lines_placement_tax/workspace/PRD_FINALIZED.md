# Surplus Lines Placement Tax API — Product Requirements Document

## 1. Introduction

When an admitted insurer will not write a risk, the coverage moves to the non-admitted — "surplus lines" — market, and with that move comes a body of statutory obligation that has nothing to do with underwriting and everything to do with paperwork. A surplus lines broker must prove that the admitted market was searched and declined it, must verify that the non-admitted insurer it intends to use actually sits on the relevant state's list of eligible carriers, must pick exactly one state as the "home state" of a risk that may span a dozen, must affix that state's statutory notices to the policy, must submit the policy to a stamping office where one exists, and must then calculate, file and remit premium tax and stamping fees on a calendar the state sets. Each of those obligations is individually mundane and collectively unforgiving: a missed declination, a lapsed licence, a carrier struck from a white list last week, a rate that moved between binding and filing — any one of them turns a clean placement into a regulatory exception.

This document specifies the API for a system that carries a surplus lines brokerage through that entire chain and keeps the arithmetic defensible afterwards. The design centres on two ideas. The first is **pinning**: every figure that a regulator might later audit — the home state, the taxation method, the premium tax rate, the stamping fee rate, the carrier's rating and surplus at the moment its security was cleared, the declination count the broker swore to — is captured at the instant the obligation crystallises and is never silently re-derived from current configuration. The second is **segregation of duties**: the compliance officer who cleared a carrier may not later swear the affidavit on a policy placed with it, and the tax filer who prepared a remittance batch may not be the one who pays it.

The system is intentionally strict about ordering. Money flows forward through placement, policy, endorsement, cancellation and filing batch, and every state transition and every rejection has a defined position in a single, normative validation ladder. Where two rules could both reject a request, the specification says which one wins. Where a calculation could be rounded at two different points, the specification says which point is correct. Implementers should treat the ordering statements in this document as part of the functional contract, not as commentary.

## 2. Global Specifications & System-Wide Principles

Every collection in this API is mounted at the top level; there is no versioning or tenancy prefix in the URL. Some read endpoints are reachable through a parent resource's path purely as a convenience channel, but identity always lives in the collection's own `id`.

### 2.1. User and Role-Based Access Control

Every request — without exception, including reads and including the logical-clock capability — must carry two headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, naming the role under which that principal is acting. If either header is absent, or present but blank, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401) before the path is even parsed.

There are exactly five roles, and their spellings are normative: `PlacementBroker`, `ComplianceOfficer`, `TaxFiler`, `StateRegulator`, and `PlatformAdmin`. A value of `X-User-Role` that is not one of those five strings is also rejected with `ERR_UNAUTHENTICATED` (HTTP 401) — an unrecognised role is treated as a failure to authenticate, not as a permission problem. Once the role is recognised, the endpoint's own authorised-role list governs: a recognised role attempting an operation that its row of the matrix in §4 does not grant receives `ERR_UNAUTHORIZED` (HTTP 403).

Identity binds to entities differently by role, and this distinction is what makes ownership checkable:

- When `X-User-Role` is `PlacementBroker`, `X-User-ID` is the `id` of the acting `Broker`. Ownership checks on any resource that references a `Broker` compare the resource's brokerage foreign key to `X-User-ID`: a placement's `broker_id`, a policy's `broker_id`, or a filing batch's `broker_id`. A broker acting on a resource that belongs to another brokerage is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403), and ownership is inherited transitively — an endorsement, cancellation or affidavit belongs to whichever brokerage owns its policy.
- When `X-User-Role` is `ComplianceOfficer`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server records it (as `reviewer_user_id` on a decided `MarketSecurityReview`, or as `signed_by_user_id` on a signed `Affidavit`) but never compares it to any entity's `id`.
- When `X-User-Role` is `TaxFiler`, `X-User-ID` is likewise an opaque operator identifier with no backing entity. It is recorded as `prepared_by_user_id` and `remitted_by_user_id` on a `FilingBatch` and compared only by value, never resolved as an entity id.
- When `X-User-Role` is `StateRegulator`, `X-User-ID` is an opaque operator identifier with no backing entity; the server does not persist it on any resource and does not compare it to any entity's `id`.
- When `X-User-Role` is `PlatformAdmin`, `X-User-ID` is an opaque operator identifier with no backing entity. `PlatformAdmin` registers brokerages, licences, state programs and carriers and amends carrier financials and state program configuration, but holds no power over any placement, policy, tax or filing operation. That exclusion is deliberate: an administrator must not be able to step around the segregation-of-duties rules.

All five roles may read every `GET` endpoint and all five may set the logical clock.

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

List endpoints accept two query parameters. `limit` bounds the number of items returned; it defaults to 10, may not be smaller than 1 and may not be larger than 100. `offset` is the number of items to skip and defaults to 0.

Unless a specific endpoint states otherwise, list results are ordered by `created_at` ascending.

List responses populate `limit`, `offset`, `total_count` and `has_more` in the `meta` object of the envelope. `total_count` reflects the number of items matching the filters before pagination is applied, and `has_more` is true when items remain beyond the current window.

### 2.4. The Logical Clock

Every time-dependent rule in this API reads a server-held **logical clock**, never the host's wall clock. A freshly started process holds the clock at `2026-08-01T00:00:00Z`. Any of the five roles may move it by supplying a `current_utc` instant to the clock-setting capability, whose response echoes the `current_utc` now in force.

Moving the clock takes effect immediately and simultaneously for every rule that depends on it. A `BrokerLicense`'s computed `status` is re-derived on the next read. The ninety-day diligent-search lookback window slides. A filing batch's lateness determination, the `signed_at` recorded on an affidavit, the `stamping_submitted_at` recorded on a policy, the `removed_on` written by a cascaded white-list removal, and the filing period a new tax filing line falls into are all read from the clock at the moment of the operation and are not revisited afterwards. Where such a field stores an instant rather than a derived value — the `signed_at` on an affidavit, the `stamping_submitted_at` on a policy, and a `removed_on` that is defaulted from the clock, whether written by a direct removal or by the decline cascade — it carries the clock's value verbatim: exactly the string the clock-setting capability echoes as `current_utc`, not re-serialised into the three-fractional-digit form §2.5 requires of `created_at` and `updated_at`. Before the clock has been moved that string is `2026-08-01T00:00:00.000Z`.

### 2.5. Record Identity, Audit Fields and Version Semantics

All fifteen resource types in this system — brokerages, broker licences, state programs, carriers, carrier eligibilities, market security reviews, placements, declinations, policies, policy state allocations, endorsements, cancellations, tax filing lines, filing batches and affidavits — carry the same four system-managed properties:

- `id` (string): a server-minted UUID. It carries no type prefix and no embedded meaning.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording when the record was first persisted.
- `updated_at` (string): an ISO 8601 UTC timestamp with three fractional digits, refreshed on every mutation of the record.
- `version` (integer): a counter that increments by exactly 1 on every mutation of the record.

"Mutation" includes writes the server performs on its own initiative. When issuing a policy advances the parent placement's `status`, the placement's `version` increments and its `updated_at` refreshes. When a declined market security review strikes a carrier from a state's white list, each affected eligibility row's `version` increments. Derived-money refreshes count too: recomputing a policy's `total_tax_cents` after an endorsement issues is a mutation of the policy.

### 2.6. Money, Rates and Rounding Discipline

All monetary amounts in this system are integer counts of cents. There are no fractional-cent fields and no floating-point money in request or response bodies. Where a rule requires rounding a non-integer intermediate to cents, the method is always **round half up**: round the exact rational value to the nearest integer, with ties resolved away from zero.

Two non-money quantities carry their own precision. A state program's `premium_tax_rate` and `stamping_fee_rate` are decimal fractions expressed to at most six decimal places, with `premium_tax_rate` between 0 and 0.15 inclusive and `stamping_fee_rate` between 0 and 0.05 inclusive. A policy's `min_earned_premium_pct` is a fraction between 0 and 1 inclusive expressed to at most four decimal places. An allocation row's `allocation_pct` is a computed fraction rounded half up to exactly four decimal places.

**The rounding order is normative and is not interchangeable with any equivalent-looking alternative.** Wherever an amount is apportioned across states and then taxed, the per-state amount is rounded to whole cents first, the per-state tax is then computed from that rounded amount and itself rounded to whole cents, and only then are the per-state figures summed into a total. Summing exact per-state products and rounding once at the end produces a different — and incorrect — answer.

Wherever integer cents are apportioned across states, the distribution uses the **largest-remainder** method against the *exact* rational share, never against the four-decimal `allocation_pct` that is displayed. Each state first receives the floor of its exact share. The cents left over after all floors are handed out are then distributed one cent at a time, in descending order of the fractional part that was truncated, with ties broken by `state_code` in ascending ASCII order. This guarantees that the apportioned parts sum exactly to the amount being apportioned, with no residual cent lost or invented.

### 2.7. Rate Pinning and Configuration Drift

State program configuration is mutable, and it will drift. A `PlatformAdmin` may amend a program's `premium_tax_rate`, `stamping_fee_rate`, `stamping_fee_cap_cents`, `stamping_office_required`, `diligent_search_min_declinations`, `filing_deadline_days` or `required_notice_codes` at any time. Such an amendment changes only the fields actually supplied, increments the program's `version`, and — critically — **has no retroactive effect on any allocation row already created.**

Pinning is implemented by copying values onto the records that depend on them, at the instant the dependency forms:

- A placement's `home_state` is resolved once, at placement creation, and is never recomputed.
- A policy's `home_state` is copied from its placement at issuance, and its `allocation_method_applied` is copied from that home state's program `allocation_method` at issuance. Every later tax computation on that policy uses the pinned method, so an endorsement can never silently move the policy between taxation regimes.
- Each allocation row records `premium_tax_rate_applied` and `stamping_fee_rate_applied`, copied from that state's program at the instant the row is first created. Every subsequent recomputation — endorsement issue, endorsement void, cancellation processing — reuses those pinned rates, never the program's current ones.
- A market security review records `capital_surplus_at_review_cents` and `rating_at_review`, copied from the carrier at the instant the review is decided.
- A placement's `declination_count` is pinned at the instant the diligent search is completed.

The one value that is deliberately *not* pinned is a program's `stamping_fee_cap_cents`, which is consulted at each recomputation of a stamping fee rather than copied onto the row.

### 2.8. Cascade Propagation

Several operations in this system reach well beyond the record they name, and the depth of that reach is part of the specification. Two chains deserve advance warning.

Declining a market security review is a three-hop cascade. The first hop writes the review's own `status`. The second hop, caused by the first, writes the carrier's `security_status` and increments the carrier's `version`. The third hop, caused by the second, sweeps every white-list entry of that carrier whose `listing_status` is `WHITE_LISTED`, setting each to `REMOVED`, stamping each `removed_on` with the current logical clock and incrementing each row's `version`; the rows are processed in ascending order of the `state_code` of the state program each row points at.

Issuing an endorsement is a four-hop cascade. The first hop writes the endorsement's own `status`. The second hop, caused by the first, recomputes the policy's `gross_premium_cents` and `taxable_premium_cents` from the full set of issued endorsements. The third hop, caused by the second, recomputes every allocation row of the policy in place and refreshes `total_tax_cents` and `total_stamping_fee_cents` on the policy. The fourth hop, caused by the third, emits a tax filing line for each state whose figures actually moved.

A policy is unusual in carrying **four independent state dimensions on one record**: `status`, `compliance_status`, `tax_status` and `stamping_status`. They advance separately and no ordering between them is implied. A policy may be `COMPLIANT` while its `tax_status` is still `UNCALCULATED`, or `REMITTED` while its `compliance_status` is still `PENDING_NOTICES`. When a single request advances two dimensions — processing a cancellation moves both `status` and `tax_status`; a stamping rejection moves both `stamping_status` and `compliance_status` — the policy's `version` still increments by exactly 1 for that request.

### 2.9. Reverse-Reachability Reads and Path Resolution

No business entity in this system is nested inside another's URL for identity purposes; every collection sits at the top level and every record is addressable by its own `id`. Certain reads and certain creates are nonetheless exposed underneath a parent — a brokerage's licences, a placement's declinations, a policy's allocations, endorsements, cancellations and affidavits, a carrier's security reviews. These are reverse-reachability channels: the parent supplies the filter or the foreign key, not the identity.

When a path carries a templated segment, existence is resolved **left to right**, and the first unresolvable segment determines the error. A request naming an unknown policy and then an unknown endorsement reports the policy's absence. The 404 vocabulary is one error per entity: `ERR_BROKER_NOT_FOUND`, `ERR_STATE_PROGRAM_NOT_FOUND`, `ERR_CARRIER_NOT_FOUND`, `ERR_CARRIER_ELIGIBILITY_NOT_FOUND`, `ERR_MARKET_SECURITY_REVIEW_NOT_FOUND`, `ERR_PLACEMENT_NOT_FOUND`, `ERR_DECLINATION_NOT_FOUND`, `ERR_POLICY_NOT_FOUND`, `ERR_ENDORSEMENT_NOT_FOUND`, `ERR_CANCELLATION_NOT_FOUND`, `ERR_TAX_FILING_LINE_NOT_FOUND`, `ERR_FILING_BATCH_NOT_FOUND` and `ERR_AFFIDAVIT_NOT_FOUND`.

The same vocabulary covers foreign keys supplied in a request body, which are resolved **after** every path segment and **in the field order the endpoint declares**. Policy issuance declares `placement_id` before `carrier_id`, so a request naming both an unknown placement and an unknown carrier reports `ERR_PLACEMENT_NOT_FOUND`. Adding a white-list entry declares `carrier_id` before `state_program_id`. Opening a filing batch declares `state_program_id` before `broker_id`. An endorsement's `supersedes_endorsement_id`, when supplied and unresolvable, reports `ERR_ENDORSEMENT_NOT_FOUND`.

### 2.10. Stale-View Rejection on Version-Guarded Writes

Three write operations are guarded by optimistic concurrency control. Each requires the client to declare, as a non-optional field of the request body, the `version` of a *parent* record that it last observed. If the declared value does not equal that parent's current `version`, the write is refused: the client's view of the parent predates some other writer's change, and proceeding would let it act on facts it never saw.

- Issuing a policy requires `expected_placement_version`, matching the target placement's current `version`. A mismatch is rejected with `ERR_STALE_PLACEMENT_VERSION` (HTTP 412). This guard matters because a single placement may legitimately carry more than one policy — successive terms, or layered coverage on the same risk — so no state precondition bars a second issuance. The version check is the only thing distinguishing a client working from a current view of the placement from one whose view predates another writer's policy issuance, declination invalidation or change request.
- Creating an endorsement requires `expected_policy_version`, matching the target policy's current `version`. A mismatch is rejected with `ERR_STALE_POLICY_VERSION` (HTTP 412). A policy legitimately carries an unbounded number of endorsements, so again no state field bars a second create; the version check is what catches a client whose premium base predates another writer's endorsement issuance, tax calculation or notice affixing.
- Deciding a market security review requires `expected_carrier_version`, matching the reviewed carrier's current `version`. A mismatch is rejected with `ERR_STALE_CARRIER_VERSION` (HTTP 412). Deciding pins the carrier's surplus and rating into the review record; if the carrier's financials were amended after the reviewer loaded them, the decision would pin figures the reviewer never evaluated. Deciding a *different* review of the same carrier is perfectly legitimate, which is why no state precondition covers this case.

No other endpoint accepts a version field, and supplying one elsewhere has no effect. Calculating a policy's tax is the instructive counter-example: it deliberately carries no version guard, because a second attempt is already barred by the tax dimension's own precondition rather than by staleness.

### 2.11. The Order of Rejection

Every request walks a single normative ladder of seventeen rungs, top to bottom, and returns on the **first** rung it violates. When a request violates two rules, the lower-numbered rung is the one reported. This ordering is not advisory; it is the difference between a correct and an incorrect implementation.

1. **Identity headers present.** Both `X-User-ID` and `X-User-Role` are non-empty strings. Applies to every endpoint. Violation: `ERR_UNAUTHENTICATED` (401). Checked before the path is inspected.
2. **Role recognised.** `X-User-Role` is one of the five declared roles. Applies to every endpoint. Violation: `ERR_UNAUTHENTICATED` (401).
3. **Role permitted.** The endpoint's authorised-role list contains the acting role, or the endpoint is open to any role. Applies to every endpoint. Violation: `ERR_UNAUTHORIZED` (403).
4. **Path existence, left to right.** Every templated path segment resolves. Applies to every endpoint with a path parameter. Violation: the entity-specific 404.
5. **Body foreign-key existence.** Every foreign key in the body resolves, in the endpoint's declared field order. Applies to every endpoint whose body contains a foreign key. Violation: the entity-specific 404. Because this rung precedes field-shape validation, an unknown `carrier_id` reports 404 rather than 400.
6. **Field shape.** Every required field is present, of the declared type, within the declared range, and a member of the declared enumeration. Applies to every endpoint. Violation: `ERR_INVALID_REQUEST` (400). This rung covers missing required fields, wrong types, out-of-range numerics, state codes that are not exactly two uppercase ASCII letters, unrecognised enum members, negative money where money must be non-negative, an `expiration_date` that is not strictly after `effective_date`, and a `removed_on` that precedes `listed_on`.
7. **Resource ownership.** When the acting role is `PlacementBroker`, the resource being written belongs to that brokerage — the relevant `broker_id` equals `X-User-ID`. Violation: `ERR_NOT_RESOURCE_OWNER` (403). Because ownership is checked *after* shape, a malformed payload aimed at someone else's placement reports 400. This rung guards exactly twelve operations: beginning a search, completing a search, recording a declination, issuing a policy, affixing notices, creating an endorsement, requesting a cancellation, drafting an affidavit, issuing an endorsement, voiding an endorsement, processing a cancellation, and signing an affidavit.
8. **Stale parent version.** Where the endpoint declares a version field, it matches the parent's current `version`. Applies to policy issuance, endorsement creation and review decision. Violation: the relevant 412 error from §2.10. Stale-version rejection precedes every state and business check, so a client holding an outdated view is told to refresh rather than told its business intent is invalid.
9. **State legality.** The subject record is in a state from which the requested transition is declared. Applies to every state-transition endpoint. Violation: `ERR_INVALID_STATE` (409) unless a more specific state error covers the case — `ERR_PLACEMENT_NOT_BINDABLE` when a policy is issued against a placement that is neither `SEARCH_COMPLETE` nor `BOUND`; `ERR_POLICY_NOT_ISSUED` when the policy's `status` is not `ISSUED`; `ERR_TAX_NOT_CALCULATED` when the policy's `tax_status` is still `UNCALCULATED`; `ERR_NOTICES_NOT_AFFIXED` when notices have not been affixed; `ERR_REVIEW_ALREADY_OPEN` when another review of the same carrier is open; `ERR_PLACEMENT_ALREADY_BOUND` when a placement already carries a policy; `ERR_BROKER_SUSPENDED` when the brokerage is suspended; `ERR_BATCH_EMPTY` when a batch holds no lines; `ERR_ENDORSEMENT_ALREADY_REMITTED` when a voided endorsement's tax has already been paid. Re-triggering a transition on a terminal state falls here as `ERR_INVALID_STATE`, as does any repeat of a once-only action such as calculating a policy's tax twice.
10. **Segregation of duties.** The acting `X-User-ID` is not the same principal who performed the paired earlier step. Applies to exactly two operations: remitting a filing batch, where the actor must differ from the batch's `prepared_by_user_id`; and signing an affidavit, where the actor must differ from the `reviewer_user_id` of every `APPROVED` or `CONDITIONAL` market security review of the policy's carrier. Violation: `ERR_SEGREGATION_OF_DUTIES` (409).
11. **Broker licensing.** The brokerage holds a licence of `license_type` `SURPLUS_LINES` for the relevant state whose computed `status` is `ACTIVE`. Applies to two operations: policy issuance, where the relevant state is the placement's `home_state`; and filing-batch submission, where it is the batch state's `state_code`. Violation: `ERR_BROKER_LICENSE_NOT_ACTIVE` (409). A licence whose `expires_on` is exactly the current logical clock is already `LAPSED`.
12. **Carrier security standing.** The carrier's `security_status` is `APPROVED` or `CONDITIONAL`. Applies to policy issuance. Violation: `ERR_CARRIER_NOT_SECURITY_APPROVED` (409). This rung precedes the white-list rung, so an `UNREVIEWED` carrier reports its security standing rather than its listing.
13. **Carrier white-listing.** A white-list entry exists for the carrier and the home state's program, whose `listing_status` is `WHITE_LISTED` and whose listing window contains the policy's `effective_date`. Applies to policy issuance. Violation: `ERR_CARRIER_NOT_WHITE_LISTED` (409). For this containment test the window runs from `listed_on` inclusive up to but excluding `removed_on` when `removed_on` is set, and from `listed_on` inclusive with no upper bound otherwise.
14. **Interval collision.** The requested interval does not collide with an existing occupation of the same resource. Applies to two operations. Policy terms on one placement are half-open, running from `effective_date` inclusive up to but excluding `expiration_date`, so back-to-back terms that merely touch are permitted; an intersection with an existing non-`CANCELLED` policy on the same placement is `ERR_POLICY_TERM_OVERLAP` (409). White-list windows on one carrier-and-state pair are treated as **closed** intervals from `listed_on` through `removed_on` inclusive and additionally require a thirty-day cooling-off gap following an existing window's `removed_on`, so touching windows are rejected; a collision is `ERR_ELIGIBILITY_WINDOW_CONFLICT` (409).
15. **Diligent search sufficiency.** Applies to completing a diligent search. Violation: `ERR_DILIGENT_SEARCH_INSUFFICIENT` (422). Evaluated only after the state, licensing and interval rungs have passed.
16. **Documentary completeness.** Applies to four operations: affixing notices, signing an affidavit, deciding a market security review, and recording a stamping decision. Violations are `ERR_NOTICES_INCOMPLETE`, `ERR_AFFIDAVIT_COUNT_MISMATCH`, `ERR_DECISION_SCORE_MISMATCH`, `ERR_CONDITIONS_NOTE_REQUIRED` and `ERR_REJECTION_REASON_REQUIRED` respectively (all 422). These are content-level checks that presuppose the calculation layer has already run.
17. **Money and arithmetic.** The last rung, reachable only once every structural, referential and state check has passed. Applies to remitting a batch, processing a cancellation, issuing an endorsement, voiding an endorsement, opening a placement, and calculating a policy's tax. Violations are `ERR_REMITTANCE_AMOUNT_MISMATCH`, `ERR_CANCELLATION_DATE_OUT_OF_TERM`, `ERR_FLAT_CANCELLATION_NOT_AVAILABLE`, `ERR_PREMIUM_WOULD_BE_NON_POSITIVE`, `ERR_HOME_STATE_INDETERMINATE`, `ERR_ALLOCATION_STATE_PROGRAM_MISSING` and `ERR_SUPERSEDE_TARGET_INVALID` (all 422), together with `ERR_ENDORSEMENT_ALREADY_REMITTED`, which is a **409** as §5 and rung 9 above both record.

Uniqueness conflicts sit alongside the interval rung as 409s: a second state program for an existing `state_code` is `ERR_STATE_PROGRAM_DUPLICATE`, a second carrier with an existing `naic_number` is `ERR_CARRIER_DUPLICATE`, and adding a carrier whose `capital_surplus_cents` falls below a state's `min_carrier_capital_surplus_cents` to that state's list is `ERR_CARRIER_BELOW_STATE_CAPITAL_MINIMUM`.

### 2.12. Segregation of Duties

Two separations are enforced, and both compare opaque operator identifiers by value.

The first sits on the filing calendar. Whoever prepares a batch is recorded in `prepared_by_user_id`; whoever remits it is recorded in `remitted_by_user_id`; and the second must not be the first. The second sits on affidavits. A compliance officer who decided a market security review that ended `APPROVED` or `CONDITIONAL` for a given carrier may never sign an affidavit on a policy placed with that carrier — the check compares the acting `X-User-ID` against the `reviewer_user_id` of *every* such review of that carrier, not merely the most recent one. A review that ended `DECLINED` does not create this bar, because a declined carrier cannot have been used in the first place.

## 3. Business Logic & Workflows

### 3.1. Configuring the Regulatory Landscape

Before any risk can be placed, a `PlatformAdmin` establishes the world the brokerage operates in.

A brokerage is registered with a `firm_name` — a non-empty string of at most 200 characters — and a `home_state`, given as exactly two uppercase ASCII letters, naming the state in which it holds its resident licence. A new brokerage's `status` begins at `ACTIVE`; the only other value is `SUSPENDED`, reached by an administrative suspension. A suspended brokerage cannot begin a diligent search: the attempt is rejected with `ERR_BROKER_SUSPENDED`.

Licences are recorded against the brokerage named in the path, so a licence's `broker_id` is never supplied in the payload. Each licence carries a `state_code`, a non-empty `license_number`, a `license_type` that is either `SURPLUS_LINES` or `RESIDENT_PRODUCER`, and an `expires_on` instant. A licence's `status` is never stored: it is recomputed on every read as `ACTIVE` while the logical clock is strictly before `expires_on` and `LAPSED` from the moment the clock reaches or passes it. A brokerage's licences may be listed and narrowed by `license_type` or by `state_code`.

A state program is the configuration record for one state's surplus lines regime, and its `state_code` must be globally unique — a duplicate is `ERR_STATE_PROGRAM_DUPLICATE`. A program declares its `premium_tax_rate` and `stamping_fee_rate`; an optional `stamping_fee_cap_cents`, which is a per-allocation ceiling on the stamping fee in cents and which defaults to null meaning uncapped; a boolean `stamping_office_required` saying whether policies homed in this state must go to a stamping office; an `allocation_method` of either `HOME_STATE_SINGLE` or `ALLOCATED_MULTI`, which selects the taxation variant the state applies to multi-state risks it is the home state of; a `diligent_search_min_declinations` count, at least zero, that a search must reach before it may be completed; a boolean `export_list_exempts_search` saying whether an export-list risk escapes that count; a `filing_frequency` of `MONTHLY` or `QUARTERLY`; a `filing_deadline_days` count, at least zero, of calendar days after a filing period closes by which the batch is due; two independent booleans, `return_premium_tax_refundable` and `return_premium_stamping_refundable`, deciding whether return premium generates a negative premium tax line and a negative stamping fee line respectively; a `min_carrier_capital_surplus_cents` floor for listability in the state; and a `required_notice_codes` array of non-empty uppercase notice codes, possibly empty, that must be affixed to any policy homed there.

### 3.2. Admitting a Non-Admitted Insurer

A carrier record describes a non-admitted insurer by its `naic_number`, which must be globally unique — a duplicate is `ERR_CARRIER_DUPLICATE` — its `legal_name`, its `domicile_type` of either `US_STATE` or `ALIEN`, its `capital_surplus_cents`, and its `am_best_rating`, drawn from `A_PLUS_PLUS`, `A_PLUS`, `A`, `A_MINUS`, `B_PLUS_PLUS`, `B_PLUS` and `NR`. Two optional fields complete the picture: `trust_fund_cents`, the US trust fund balance in cents, defaulting to 0 and relevant only to alien insurers; and `naic_quarterly_listing`, defaulting to false, recording whether the insurer appears on the NAIC quarterly listing of alien surplus lines insurers. A new carrier's `security_status` is `UNREVIEWED`, and that field is written by nothing except a review decision. The other three values it may hold are `APPROVED`, `CONDITIONAL` and `DECLINED`.

An administrator may amend a carrier's `capital_surplus_cents`, `am_best_rating`, `trust_fund_cents` or `naic_quarterly_listing`. Only supplied fields change, `security_status` is explicitly *not* re-derived, and the carrier's `version` increments. This is the only way a carrier's version advances outside a security decision, and it is precisely what makes a pending decision stale.

**The market security review.** A `ComplianceOfficer` opens a review against the carrier named in the path, so the review's `carrier_id` comes from the path rather than the body. A new review is `DRAFT`, with `score` at 0 and `variant_applied` null; the pinned fields `capital_surplus_at_review_cents`, `rating_at_review` and `reviewer_user_id` and the free-text `conditions_note` are all null. Reviews of a carrier may be listed and narrowed by `status`.

Starting the review advances `DRAFT → UNDER_REVIEW` and is where the score is computed. Two preconditions guard it: no other review of the same carrier may already be `UNDER_REVIEW`, else `ERR_REVIEW_ALREADY_OPEN`, and the carrier must have a `capital_surplus_cents` value on record. The `variant_applied` is decided first: it becomes `RECERTIFICATION` when at least one earlier review of the same carrier has reached `APPROVED`, and `INITIAL_REVIEW` otherwise. The review's `version` increments.

The score itself is a sum of four components, each an integer point count, with no rounding anywhere. **Rating points** come from a fixed table: 40 for `A_PLUS_PLUS`, 35 for `A_PLUS`, 30 for `A`, 25 for `A_MINUS`, 15 for `B_PLUS_PLUS`, 10 for `B_PLUS`, and 0 for `NR`. **Capital points** come from three tier floors, each comparison being "at or above": a carrier holding fifty million dollars or more of capital and surplus — that is, at least 5,000,000,000 cents — earns 40 points; one holding at least fifteen million dollars, or 1,500,000,000 cents, earns 30; one holding at least five million dollars, or 500,000,000 cents, earns 20; and anything below the lowest floor earns the floor allowance of 5 points. A carrier sitting exactly on a tier floor earns that tier's points. **Trust points** are 15 for a carrier whose `domicile_type` is `US_STATE`, on the strength of its domiciliary regulator; an `ALIEN` carrier earns those same 15 points only when its `trust_fund_cents` is at least the US trust minimum of five million four hundred thousand dollars — 540,000,000 cents — and 0 otherwise, treating a null trust balance as zero. **Listing points** are 5 when `naic_quarterly_listing` is true and 0 when it is false. The sum of those four components is the review's base figure.

Under the `INITIAL_REVIEW` variant the `score` is that base figure exactly; no history is consulted. Under the `RECERTIFICATION` variant the base figure is reduced by a drift penalty that punishes deterioration since the last clearance. The system locates the carrier's review with `status` `APPROVED` and the greatest `created_at`, and forms a prior subscore by adding the rating points of that review's pinned `rating_at_review` to the capital-tier points its pinned `capital_surplus_at_review_cents` would earn under the same three tier floors. It forms a current subscore by adding the carrier's present rating points to its present capital points. The drift penalty is the amount by which the prior subscore exceeds the current subscore — zero if the current subscore is equal or higher — multiplied by two. The `score` is the base figure minus that penalty, floored at zero. Identical carrier financials therefore score strictly lower under `RECERTIFICATION` than under `INITIAL_REVIEW` whenever the carrier has slipped, which can move the same carrier from `APPROVED` into `CONDITIONAL` or `DECLINED`.

**The decision** is branching, and the reviewer supplies it explicitly as a `decision` of `APPROVE`, `CONDITION` or `DECLINE`, together with `expected_carrier_version` and, where relevant, a `conditions_note`. `conditions_note` is optional and carries no field-shape non-emptiness check of its own: a value that is empty or contains only whitespace still passes the field-shape rung, and is simply treated as absent by the `CONDITION` branch that requires it. The server refuses a decision the score does not support, with `ERR_DECISION_SCORE_MISMATCH`: `APPROVE` requires a score of at least 70, `CONDITION` requires a score of at least 50 and strictly below 70, and `DECLINE` requires a score strictly below 50. All three branches pin `reviewer_user_id` to the acting `X-User-ID`, pin `capital_surplus_at_review_cents` from the carrier's current `capital_surplus_cents`, pin `rating_at_review` from the carrier's current `am_best_rating`, mirror the outcome onto the carrier's `security_status`, and increment both the review's `version` and the carrier's `version` by one each. Beyond that the branches differ:

- `UNDER_REVIEW → APPROVED` sets the carrier's `security_status` to `APPROVED`.
- `UNDER_REVIEW → CONDITIONAL` additionally requires the supplied `conditions_note` to be a non-empty string, else `ERR_CONDITIONS_NOTE_REQUIRED`; it stores that note on the review and sets the carrier's `security_status` to `CONDITIONAL`.
- `UNDER_REVIEW → DECLINED` sets the carrier's `security_status` to `DECLINED` and then, as a consequence of that carrier-level write, strikes the carrier from every state list it appears on: each white-list entry of the carrier whose `listing_status` is `WHITE_LISTED` moves to `REMOVED`, has its `removed_on` set to the current logical clock, and has its `version` incremented, processed in ascending order of the `state_code` of the state program each entry points at.

All three decision outcomes are terminal for the review.

**The white list.** A `StateRegulator` adds a carrier to a state's list of eligible surplus lines insurers by supplying `carrier_id`, `state_program_id` and a `listed_on` instant from which the entry is effective. The new entry's `listing_status` is `WHITE_LISTED` and its `removed_on` is null. Two gates apply: the carrier's `capital_surplus_cents` must be at or above the state's `min_carrier_capital_surplus_cents`, else `ERR_CARRIER_BELOW_STATE_CAPITAL_MINIMUM`; and the new window must not collide with an existing window on the same carrier-and-state pair under the closed-interval-plus-thirty-day-cooling-off semantics of §2.11, else `ERR_ELIGIBILITY_WINDOW_CONFLICT`. Entries may be listed and narrowed by `carrier_id`, `state_program_id` or `listing_status`.

A regulator may also remove an entry directly, advancing `WHITE_LISTED → REMOVED` and incrementing the entry's `version`. A `removed_on` may be supplied; when it is, it must be at or after `listed_on`, else `ERR_INVALID_REQUEST`, and when it is omitted the current logical clock is used. `REMOVED` is terminal.

### 3.3. Opening a Placement and Fixing the Home State

A `PlacementBroker` opens a placement file for a risk. The `broker_id` is never supplied — it is taken from the acting `X-User-ID`. The payload carries the `insured_name`, a non-empty string; the `principal_place_of_business_state`, two uppercase ASCII letters; a `coverage_class` drawn from `PROPERTY`, `GENERAL_LIABILITY`, `PROFESSIONAL_LIABILITY`, `EXCESS_CASUALTY` and `INLAND_MARINE`; an optional `is_export_list_risk` boolean defaulting to false, asserting that the coverage appears on the home state's export list; and a `state_exposures` array describing where the insured value actually sits. That array must be supplied — a missing or null `state_exposures` is a field-shape failure reported as `ERR_INVALID_REQUEST`, whereas an array that is present but empty passes field-shape validation and is instead refused by the first step of the home-state waterfall below — and each entry pairs a `state_code` of exactly two uppercase ASCII letters — unique within the array — with a non-negative integer `insured_value_cents`.

**Determining the home state** is the first substantive calculation in the system, and it runs exactly once, at creation. Every downstream tax, notice and stamping obligation hangs off the result, so the placement's `home_state` is never recomputed afterwards. The waterfall has three steps. First, an empty `state_exposures` array is refused outright with `ERR_HOME_STATE_INDETERMINATE`. Second, the insured's principal place of business wins if — and only if — it carries real exposure: the system looks for an exposure entry whose `state_code` equals `principal_place_of_business_state` and whose `insured_value_cents` is **strictly greater than zero**, and if at least one such entry exists, the `home_state` is the principal place of business. An exposure entry for the principal place of business with an insured value of exactly zero does *not* qualify. Third, failing that, the greatest insured value wins: among only those entries whose `insured_value_cents` is strictly greater than zero, the system finds the largest `insured_value_cents` and takes the alphabetically smallest `state_code` among the entries holding that largest value; if no entry has a positive insured value at all, the placement is refused with `ERR_HOME_STATE_INDETERMINATE`. Separately, the placement's `total_insured_value_cents` is the exact sum of `insured_value_cents` across *every* entry in the array, including entries whose value is zero, with no rounding.

A new placement's `declination_count` is 0 and its `status` is `DRAFT`. Placements may be retrieved individually and listed, narrowed by `broker_id`, `home_state` or `status`.

### 3.4. Documenting the Diligent Search

The placement lifecycle is a revision loop rather than a straight line. `DRAFT → SEARCH_IN_PROGRESS` opens the search; it requires that the placement's `broker_id` equals the acting `X-User-ID` and that the owning brokerage's `status` is `ACTIVE`, and it increments the placement's `version`. `SEARCH_IN_PROGRESS → SEARCH_COMPLETE` asserts that the search is finished. `SEARCH_COMPLETE → CHANGES_REQUESTED`, available only to a `ComplianceOfficer`, sends a completed search back for revision; it requires that no policy yet references this placement, else `ERR_PLACEMENT_ALREADY_BOUND`, and it resets the placement's `declination_count` to 0 before setting the status and incrementing the `version`. `CHANGES_REQUESTED → SEARCH_IN_PROGRESS` re-opens the search under the same two ownership-and-active-brokerage preconditions as the first opening, closing a cycle — `SEARCH_COMPLETE → CHANGES_REQUESTED → SEARCH_IN_PROGRESS → SEARCH_COMPLETE` — that may be traversed any number of times.

**Declinations** are recorded against the placement named in the path, so `placement_id` comes from the path. Each declination names the declining admitted insurer via `admitted_carrier_name` in the payload — the persisted record exposes that value as `admitted_insurer_name`, and carries the declining insurer's `naic_number` where one is supplied — together with the `state_code` in which the insurer declined, a `reason_code` drawn from `NO_APPETITE`, `CAPACITY`, `UNDERWRITING`, `RATE` and `NOT_LICENSED_FOR_CLASS`, and the `declined_on` instant. A new declination's `status` is `RECORDED`. A `ComplianceOfficer` may strike one from the record, advancing `RECORDED → INVALIDATED` and incrementing the declination's `version`; the strike is refused with `ERR_PLACEMENT_ALREADY_BOUND` when the parent placement's `status` is already `BOUND`. An `INVALIDATED` declination stops counting toward the search, and `INVALIDATED` is terminal. Declinations under a placement may be listed and narrowed by `status` or `state_code`.

**Sufficiency** is evaluated when the broker completes the search, and it is strict about what counts. A declination is *valid* only if all four of the following hold: its `status` is `RECORDED`; its `reason_code` is anything other than `NOT_LICENSED_FOR_CLASS`, because an admitted carrier that is not licensed for the class is evidence of nothing about the market's willingness to write the risk; its `state_code` equals the placement's `home_state`, so declinations obtained elsewhere do not travel; and its `declined_on` is **at or after** a cutoff computed as the current logical clock minus a lookback of exactly 90 calendar days — a declination landing exactly on the cutoff instant still counts. The count of valid declinations is compared against the home state's `diligent_search_min_declinations`, and the search is sufficient when the count is greater than or equal to that minimum. The one bypass is the export list: when the placement's `is_export_list_risk` is true *and* the home state's `export_list_exempts_search` is also true, the search is sufficient regardless of the count. An insufficient search is refused with `ERR_DILIGENT_SEARCH_INSUFFICIENT`.

Completing the search additionally requires that the placement's `broker_id` equals the acting `X-User-ID` and that a state program exists whose `state_code` equals the placement's `home_state`. On success, the placement's `declination_count` is set to the valid count just computed — pinning it for the affidavit that will later have to match it — the `status` becomes `SEARCH_COMPLETE`, and the `version` increments.

### 3.5. Binding the Policy

Issuing a policy is the densest gate in the system. A `PlacementBroker` submits `placement_id`, `carrier_id`, a `policy_number` that must be non-empty and globally unique, an `effective_date`, an `expiration_date` that must be strictly after it, an `original_gross_premium_cents` that must be strictly greater than zero, and `expected_placement_version`. Three optional money fields round out the payload: `policy_fee_cents`, the carrier's policy fee, defaulting to 0 and non-negative; `broker_fee_cents`, the surplus lines broker's own fee, defaulting to 0 and non-negative; and `min_earned_premium_pct`, defaulting to 0, the fraction of taxable premium the carrier retains as minimum earned premium if the policy is later cancelled.

The gates run in the order fixed by §2.11: ownership of the placement, then the stale-placement-version check, then the placement's own state, then the brokerage's surplus lines licensing in the home state, then the carrier's security standing, then the carrier's white-listing, and finally term overlap. The placement must be `SEARCH_COMPLETE` or already `BOUND`, else `ERR_PLACEMENT_NOT_BINDABLE`. This is deliberate: a risk file legitimately carries successive terms and layered policies, so a placement that is already `BOUND` remains bindable, further issuances succeed, and the status simply stays at `BOUND` — while still incrementing the placement's `version` on *every* issuance, including those that leave the status unchanged. That is exactly what makes the term-overlap rule and the stale-placement-version rule reachable in the first place.

Issuance pins a great deal. The policy's `broker_id` is copied from the placement's `broker_id`; its `home_state` is copied from the placement's `home_state`; and its `allocation_method_applied` is copied from the home state's program `allocation_method`, taking the value `HOME_STATE_SINGLE` or `ALLOCATED_MULTI`. Its `gross_premium_cents` starts equal to `original_gross_premium_cents` — that original figure is supplied once and is immutable thereafter, while `gross_premium_cents` is thereafter always the original plus the sum of `premium_delta_cents` across every `ISSUED` endorsement on the policy. Its `taxable_premium_cents`, `total_tax_cents` and `total_stamping_fee_cents` all start at 0 and stay there until the tax is calculated. Its `notice_codes_affixed` starts as an empty array and its `stamping_submitted_at` is null.

The four state dimensions are initialised as follows: `status` is `ISSUED`, with `CANCELLED` the only other value and terminal; `compliance_status` is `PENDING_NOTICES`, out of `PENDING_NOTICES`, `NOTICES_AFFIXED`, `COMPLIANT` and the terminal `DEFICIENT`; `tax_status` is `UNCALCULATED`, out of `UNCALCULATED`, `CALCULATED`, `ADJUSTED`, `FILED` and `REMITTED`, none of which is terminal; and `stamping_status` is `PENDING` when the home state's `stamping_office_required` is true and `NOT_REQUIRED` when it is false, out of `NOT_REQUIRED`, `PENDING`, `SUBMITTED`, `ACCEPTED` and `REJECTED`, of which `NOT_REQUIRED`, `ACCEPTED` and `REJECTED` are terminal.

Policies may be retrieved individually and listed, narrowed by `placement_id`, `carrier_id`, `broker_id` or `tax_status`.

### 3.6. Notices, Affidavits and the Stamping Office

**Affixing notices** advances the compliance dimension `PENDING_NOTICES → NOTICES_AFFIXED`. The owning broker supplies a `notice_codes` array; the request is refused with `ERR_NOTICES_INCOMPLETE` unless that array contains every code listed in `required_notice_codes` on the program whose `state_code` equals the policy's `home_state`. Extra codes beyond the required set are permitted. On success the policy's `notice_codes_affixed` becomes the supplied array de-duplicated and sorted in ascending ASCII order, and the policy's `version` increments.

**Affidavits** are drafted against the policy named in the path, so `policy_id` comes from the path. Each carries an `affidavit_type` of either `DILIGENT_SEARCH` or `PREMIUM_TAX` and a `declination_count_attested`, a non-negative integer, being the number of admitted-market declinations the broker swears to. A new affidavit's `status` is `DRAFT`, with `signed_by_user_id` and `signed_at` both null. Affidavits under a policy may be listed and narrowed by `affidavit_type` or `status`.

Signing advances `DRAFT → SIGNED` and is open to a `PlacementBroker` or a `ComplianceOfficer`. Three preconditions apply. When the acting role is `PlacementBroker`, the policy's `broker_id` must equal the acting `X-User-ID`. The acting `X-User-ID` must differ from the `reviewer_user_id` of every `APPROVED` or `CONDITIONAL` market security review whose `carrier_id` equals the policy's `carrier_id`, else `ERR_SEGREGATION_OF_DUTIES`. And `declination_count_attested` must equal the `declination_count` recorded on the policy's placement, else `ERR_AFFIDAVIT_COUNT_MISMATCH` — which is why a change request that zeroes the placement's count invalidates any affidavit drafted against the old figure. On success the affidavit's `signed_by_user_id` is set to the acting `X-User-ID`, its `signed_at` to the current logical clock, its `status` to the terminal `SIGNED`, and its `version` increments. Additionally, when the `affidavit_type` is `DILIGENT_SEARCH` and the policy's `compliance_status` is `NOTICES_AFFIXED` at that moment, the compliance dimension advances `NOTICES_AFFIXED → COMPLIANT` and the policy's `version` increments by one.

**Stamping submission** advances the stamping dimension `PENDING → SUBMITTED` and is a `TaxFiler` action. Two preconditions guard it: the policy's `compliance_status` must be `NOTICES_AFFIXED` or `COMPLIANT`, else `ERR_NOTICES_NOT_AFFIXED` — so a policy still at `PENDING_NOTICES`, or already `DEFICIENT`, cannot be submitted — and the policy's `tax_status` must not still be `UNCALCULATED`, else `ERR_TAX_NOT_CALCULATED`. On success the policy's `stamping_submitted_at` is set to the current logical clock and its `version` increments.

**The stamping decision** is rendered by a `StateRegulator` and carries a `decision` of `ACCEPT` or `REJECT` plus an optional `rejection_reason`. `rejection_reason` carries no field-shape non-emptiness check of its own: a value that is empty or contains only whitespace still passes the field-shape rung, and is simply treated as absent by the `REJECT` branch that requires it. On `ACCEPT` the stamping dimension advances `SUBMITTED → ACCEPTED`, `compliance_status` is left untouched, and the policy's `version` increments. On `REJECT` the `rejection_reason` must be a non-empty string, else `ERR_REJECTION_REASON_REQUIRED`; the stamping dimension advances `SUBMITTED → REJECTED`, and the same request also drives the independent compliance dimension to `DEFICIENT` — from `NOTICES_AFFIXED → DEFICIENT` or from `COMPLIANT → DEFICIENT`, whichever applies — with the policy's `version` incrementing by one for the request as a whole. Both branches require the policy's `stamping_status` to be `SUBMITTED` beforehand.

### 3.7. Calculating Premium Tax and the Stamping Fee

A `TaxFiler` calculates the tax, advancing the tax dimension `UNCALCULATED → CALCULATED`. Two preconditions apply: the policy's `status` must be `ISSUED`, and a state program must exist for the policy's `home_state` and for every state the selected variant allocates premium to, else `ERR_ALLOCATION_STATE_PROGRAM_MISSING`. This operation carries no version guard at all; a second attempt is barred by the tax dimension's own precondition and reports `ERR_INVALID_STATE`.

**The taxable base** comes first. The taxable premium is `gross_premium_cents` plus `policy_fee_cents`. The policy fee is part of the consideration for the insurance and is taxable. The `broker_fee_cents` is compensation to the broker and is **never** included in the taxable premium — not at issuance, not at endorsement, not at cancellation.

**Variant selection** then reads the `allocation_method_applied` pinned onto the policy at issuance, and the two variants are genuinely different regimes.

Under `HOME_STATE_SINGLE`, exactly one allocation row is created, for the policy's `home_state`, with `allocation_pct` of 1.0000 and `allocated_premium_cents` equal to the entire taxable premium — regardless of how many states hold exposure on the underlying risk. That single row is taxed at the home state's `premium_tax_rate` and is subject to the home state's `stamping_fee_rate` and `stamping_fee_cap_cents`. Its `allocation_basis` records `HOME_STATE_SINGLE`.

Under `ALLOCATED_MULTI`, one allocation row is created per state in the placement's `state_exposures` whose `insured_value_cents` is strictly greater than zero, and the rows are emitted in ascending `state_code` order. Each row's `allocation_pct` is that state's `insured_value_cents` divided by the total insured value across those positive-exposure states, rounded half up to four decimal places — this is the displayed percentage only. The cents themselves are apportioned by the largest-remainder method of §2.6 against the exact rational share of the taxable premium, never by multiplying the rounded four-decimal percentage: each state first takes the floor of the taxable premium multiplied by its `insured_value_cents` and divided by the positive-exposure total, and the cents left over are handed out one at a time in descending order of truncated fractional part with ties broken by ascending `state_code`. The result is that `allocated_premium_cents` across the rows sums exactly to the taxable premium. Each row is taxed at its **own** state's `premium_tax_rate` and subject to its **own** state's `stamping_fee_rate` and `stamping_fee_cap_cents`. Each row's `allocation_basis` records `ALLOCATED_MULTI`. For identical policy inputs the two variants produce different totals whenever any non-home state's rate differs from the home state's.

**Per-row tax and fee** are then derived, and the rates are pinned onto the row at this moment: `premium_tax_rate_applied` takes the state's current `premium_tax_rate` and `stamping_fee_rate_applied` takes its current `stamping_fee_rate`. The row's `tax_cents` is the row's `allocated_premium_cents` multiplied by its `premium_tax_rate_applied`, rounded half up to whole cents. The row's `stamping_fee_cents` is zero outright when that state's `stamping_office_required` is false. Otherwise an uncapped figure is computed as the row's `allocated_premium_cents` multiplied by its `stamping_fee_rate_applied`, rounded half up to whole cents; when the state's `stamping_fee_cap_cents` is null the uncapped figure stands, and when a cap is configured the row takes the smaller of the uncapped figure and the cap.

The policy's `total_tax_cents` and `total_stamping_fee_cents` are the sums of `tax_cents` and `stamping_fee_cents` across the rows — rounded per row first, summed second, per §2.6.

Calculation also opens the ledger. One tax filing line with `line_type` `NEW_BUSINESS` and `status` `OPEN` is created per allocated state, in ascending `state_code` order, carrying that state's `taxable_premium_cents`, `tax_cents` and `stamping_fee_cents`. Each line's `policy_id` and `state_program_id` are set from the policy and the allocated state's program; its `filing_batch_id`, `source_endorsement_id` and `source_cancellation_id` are null; and its `period_key` is derived from the logical clock at the moment the line is created, formatted according to that state's `filing_frequency` — `YYYY-MM` for `MONTHLY` and `YYYY-Qn` for `QUARTERLY`. Finally the policy's `tax_status` becomes `CALCULATED` and its `version` increments.

A policy's allocation rows may be listed and narrowed by `state_code`; each row exposes the `policy_id` it belongs to alongside the rates pinned at calculation time. Filing lines may be retrieved individually or listed and narrowed by `policy_id`, `state_program_id`, `filing_batch_id`, `source_endorsement_id`, `source_cancellation_id`, `status`, `period_key` or `line_type`. A line's `status` moves through `OPEN`, `BATCHED`, `FILED`, `REMITTED` and, where a line is superseded, `VOIDED`.

### 3.8. Endorsements, Cancellations and Return-Premium Adjustments

**Drafting an endorsement.** The owning broker creates an endorsement against the policy named in the path, so `policy_id` comes from the path, supplying an `endorsement_type` of `PREMIUM_INCREASE`, `PREMIUM_DECREASE`, `EXPOSURE_CHANGE` or `ADMINISTRATIVE`; a signed `premium_delta_cents`, which must be exactly 0 for `ADMINISTRATIVE`, strictly greater than 0 for `PREMIUM_INCREASE` and strictly less than 0 for `PREMIUM_DECREASE`; an `effective_date` that must fall within the policy term; an optional `supersedes_endorsement_id` naming an earlier endorsement on the same policy that this one replaces, defaulting to null; and `expected_policy_version`. The server assigns a `sequence_number` — a one-based ordinal within the policy, one greater than the highest `sequence_number` already present, starting at 1 — sets `status` to `DRAFT`, and starts `tax_adjustment_cents` and `stamping_fee_adjustment_cents` at 0. Endorsements may be retrieved individually or listed and narrowed by `policy_id`, `supersedes_endorsement_id` or `status`.

**Issuing an endorsement** advances `DRAFT → ISSUED` and is where the four-hop cascade of §2.8 fires. Four preconditions guard it: the policy's `status` must be `ISSUED`, else `ERR_POLICY_NOT_ISSUED`; the policy's `tax_status` must not be `UNCALCULATED`, else `ERR_TAX_NOT_CALCULATED`; when `supersedes_endorsement_id` is non-null, the named endorsement must have `status` `ISSUED` and belong to the same policy, else `ERR_SUPERSEDE_TARGET_INVALID`; and the resulting `gross_premium_cents` must remain strictly greater than zero, else `ERR_PREMIUM_WOULD_BE_NON_POSITIVE`.

The recomputation has a pinned evaluation order, because the taxable premium feeds the allocation, the allocation feeds the per-state tax, and the per-state tax feeds the adjustment; reversing any two steps yields a different number. Before anything is touched, the policy's current `total_tax_cents` and `total_stamping_fee_cents` are snapshotted as the "before" picture. Step one recomputes `gross_premium_cents` as `original_gross_premium_cents` plus the sum of `premium_delta_cents` across the policy's endorsements whose `status` is `ISSUED` — always from the full issued set, never by incrementally adding a delta to the stored figure, and that is precisely what makes a void exactly reversible. Step two recomputes `taxable_premium_cents` as that gross premium plus `policy_fee_cents`. Step three redistributes the new taxable premium across the **pinned** allocation percentages: the percentage set is frozen at first calculation, so an `EXPOSURE_CHANGE` endorsement moves premium but never re-apportions the policy. Because four-decimal percentages need not sum to exactly one — three equal thirds pin as 0.3333 each — each row's `allocation_pct` is first divided by the sum of all the pinned percentages, and the taxable premium is then split across those normalised weights by largest remainder ordered by ascending `state_code`, so the parts sum exactly to the taxable premium. Step four re-derives each row from its own pinned rates: the row's old `tax_cents` and old `stamping_fee_cents` are remembered, `allocated_premium_cents` takes its new part, and `tax_cents` becomes that new allocated amount multiplied by `premium_tax_rate_applied`, rounded half up. The stamping fee stays at zero when the row's old `stamping_fee_cents` was zero *and* its `stamping_fee_rate_applied` is zero; otherwise an uncapped figure is computed as the new allocated amount multiplied by `stamping_fee_rate_applied`, rounded half up, and the row takes that figure when the state's `stamping_fee_cap_cents` is null or the smaller of that figure and the cap when a cap is configured. The policy's `total_tax_cents` and `total_stamping_fee_cents` are then re-summed from the rows.

Step five expresses the difference. The endorsement's `tax_adjustment_cents` is the policy's `total_tax_cents` after minus the snapshotted before, and its `stamping_fee_adjustment_cents` is the policy's `total_stamping_fee_cents` after minus its snapshotted before; either may be negative. One tax filing line with `line_type` `ENDORSEMENT`, `source_endorsement_id` set to this endorsement and `status` `OPEN` is emitted for each state whose `tax_cents` **or** `stamping_fee_cents` actually moved, in ascending `state_code` order; each such line carries as its `taxable_premium_cents` the change in that state's `allocated_premium_cents`, as its `tax_cents` that state's signed tax movement, and as its `stamping_fee_cents` that state's signed stamping movement. A state whose figures did not move gets no line. When `supersedes_endorsement_id` is non-null, the superseded endorsement is moved to `VOIDED` first and its own compensating lines are emitted before this endorsement's. Finally the policy's `tax_status` advances to `ADJUSTED` and both the endorsement's `version` and the policy's `version` increment by one each.

**Voiding an endorsement** has two quite different meanings depending on where it starts, and both are declared. From `ISSUED → VOIDED`, the void is refused with `ERR_ENDORSEMENT_ALREADY_REMITTED` when any tax filing line whose `source_endorsement_id` is this endorsement has already reached `status` `REMITTED`. Otherwise the endorsement's `status` becomes `VOIDED`; the policy's premium, allocation rows and totals are recomputed from the *remaining* issued endorsement set by exactly the procedure above; one compensating tax filing line with `line_type` `ENDORSEMENT` and `status` `OPEN` is created per affected state carrying the exact negation of the voided endorsement's per-state tax and stamping deltas; the policy's `tax_status` advances to `ADJUSTED`; and both the endorsement's `version` and the policy's `version` increment by one each. From `DRAFT → VOIDED`, there are no preconditions at all: the endorsement's `status` becomes `VOIDED`, no tax filing line is created and no policy field changes, because a draft endorsement never entered the premium base; only the endorsement's own `version` increments. `VOIDED` is terminal.

**Requesting a cancellation.** The owning broker raises a cancellation against the policy named in the path, so `policy_id` comes from the path, supplying a `cancellation_type` of `FLAT`, `PRO_RATA` or `SHORT_RATE` and a `cancellation_date` that must fall within the policy term. The new record's `status` is `REQUESTED` and all four computed money fields — `earned_premium_cents`, `return_premium_cents`, `tax_refund_cents` and `stamping_fee_refund_cents` — start at 0. Cancellations under a policy may be listed and narrowed by `status`.

**Processing the cancellation** advances `REQUESTED → PROCESSED`, which is terminal, and simultaneously drives the policy's `status` dimension `ISSUED → CANCELLED` and its `tax_status` dimension to `ADJUSTED`. Two preconditions apply: the policy's `status` must be `ISSUED`, else `ERR_POLICY_NOT_ISSUED`, and its `tax_status` must not be `UNCALCULATED`, else `ERR_TAX_NOT_CALCULATED`.

The refund arithmetic proceeds in three steps over whole calendar days. The term length is the number of whole calendar days from the policy's `effective_date` to its `expiration_date`, and the elapsed length is the number of whole calendar days from `effective_date` to `cancellation_date`; if the elapsed length is negative or exceeds the term length, the request is refused with `ERR_CANCELLATION_DATE_OUT_OF_TERM`. The unearned day count is the term length minus the elapsed length. Step one computes the unearned premium from the policy's `taxable_premium_cents` according to the cancellation type. A `FLAT` cancellation is available only on the effective date itself: if the elapsed day count is anything other than zero the request is refused with `ERR_FLAT_CANCELLATION_NOT_AVAILABLE`, and otherwise the whole taxable premium is unearned. A `PRO_RATA` cancellation makes the unearned premium the taxable premium multiplied by the unearned day count and divided by the term length, rounded half up to whole cents. A `SHORT_RATE` cancellation takes that same pro-rata figure and multiplies it by a short-rate factor of 0.90 before rounding half up to whole cents, so the carrier retains a penalty share when the insured cancels.

Step two applies the minimum earned premium floor, which is evaluated **after** the type calculation and is capable of overriding it entirely. The floor amount is the taxable premium multiplied by the policy's `min_earned_premium_pct`, rounded half up to whole cents. If the amount the carrier would otherwise earn — the taxable premium less the unearned figure — falls below that floor, the unearned figure is replaced by the taxable premium less the floor, and never allowed below zero. The cancellation's `return_premium_cents` is the resulting unearned figure and its `earned_premium_cents` is the taxable premium less that figure.

Step three refunds tax and fees per state. The returned premium is apportioned across the **same** allocation rows the policy already carries, using the pinned `allocation_pct` set normalised by the sum of those pinned percentages, split by largest remainder ordered by ascending `state_code`, so the parts sum exactly to the returned premium. For each row, the tax refund contribution is that state's part multiplied by the row's `premium_tax_rate_applied`, rounded half up — but only when that state's `return_premium_tax_refundable` is true; when it is false the contribution is zero, because premium tax already paid is non-refundable in that state. The stamping refund contribution is that state's part multiplied by the row's `stamping_fee_rate_applied`, rounded half up and then capped so that it never exceeds the row's own `stamping_fee_cents` — but only when that state's `return_premium_stamping_refundable` is true **and** the row's `stamping_fee_cents` is greater than zero; otherwise the contribution is zero. The cancellation's `tax_refund_cents` and `stamping_fee_refund_cents` are the sums of those per-state contributions, rounded per state and then summed, and both are reported on the cancellation as **positive** magnitudes.

The ledger effect is the mirror image. One tax filing line with `line_type` `CANCELLATION_RETURN`, `source_cancellation_id` set and `status` `OPEN` is created per allocated state, in ascending `state_code` order, and each carries **negative** `taxable_premium_cents`, `tax_cents` and `stamping_fee_cents`. Both the cancellation's `version` and the policy's `version` increment by one each.

**The tax dimension is cyclic.** `CALCULATED → ADJUSTED` fires whenever an endorsement is issued, an endorsement is voided or a cancellation is processed while the policy's `tax_status` is anything other than `UNCALCULATED`; the allocation rows are recomputed in place using their pinned rates, an adjusting line is created per affected state, and the policy's `version` increments. `REMITTED → ADJUSTED` closes the cycle: when an endorsement is issued or a cancellation processed after the tax has already been paid, and the adjusting event produces a non-zero tax or stamping fee delta, an adjusting line with `status` `OPEN` is created per affected state, the `tax_status` returns to `ADJUSTED` and the policy's `version` increments — so `REMITTED → ADJUSTED → FILED → REMITTED` is a legitimate and repeatable path.

### 3.9. The Filing Calendar

A `TaxFiler` opens a filing batch for exactly one state, one brokerage and one filing period, supplying `state_program_id`, `broker_id` and `period_key`. A new batch's `status` is `OPEN`, its `line_count` is 0, its `total_tax_cents`, `total_stamping_fee_cents`, `penalty_cents` and `total_due_cents` are all 0, its `late` flag is false, its `due_date` is null, and both `prepared_by_user_id` and `remitted_by_user_id` are null. Batches may be retrieved individually or listed and narrowed by `state_program_id`, `broker_id`, `status` or `period_key`.

**Preparation** advances `OPEN → PREPARED` and is where the sweep, the totals, the due date and the penalty are all determined. Its single precondition is that the batch's `period_key` matches the format the state's `filing_frequency` demands — `YYYY-MM` when the frequency is `MONTHLY`, or `YYYY-Qn` with the quarter number between 1 and 4 when the frequency is `QUARTERLY` — else `ERR_PERIOD_KEY_MALFORMED`.

The sweep reaches across policy boundaries. Every tax filing line whose `status` is `OPEN`, whose `state_program_id` equals the batch's, whose `period_key` equals the batch's, and whose policy's `broker_id` equals the batch's `broker_id` is claimed: its `filing_batch_id` is set to this batch and its `status` becomes `BATCHED`. Lines are processed in ascending `created_at` order. The batch's `line_count` is the number of lines swept, its `total_tax_cents` is the signed sum of their `tax_cents`, and its `total_stamping_fee_cents` is the signed sum of their `stamping_fee_cents`. Because return-premium lines and premium-decreasing endorsements carry negative amounts, either total may be negative.

The `due_date` is derived from the state's own calendar: take the last calendar day of the period named by `period_key`, add the state's `filing_deadline_days` calendar days, and set the instant to 23:59:59.999Z on that day. Lateness is **strictly** determined: the batch's `late` flag is true only when the current logical clock is strictly after the `due_date`, so a batch prepared at exactly the `due_date` instant is on time. When the batch is not late, `penalty_cents` is 0. When it is late, `penalty_cents` is the larger of two figures: the batch's `total_tax_cents` multiplied by a late penalty rate of 0.10 — using zero in place of a negative tax total, so a refund-heavy batch is never penalised on a negative base — rounded half up to whole cents; and a statutory floor of 2,500 cents, that is twenty-five dollars. The batch's `total_due_cents` is then its `total_tax_cents` plus its `total_stamping_fee_cents` plus its `penalty_cents`, and it may legitimately be negative when net return premium exceeds new business. Preparation records the acting `X-User-ID` as `prepared_by_user_id`, sets `status` to `PREPARED` and increments the batch's `version`.

**Submission** advances `PREPARED → SUBMITTED` and files the batch with the state. Two preconditions apply: the batch's `line_count` must be greater than 0, else `ERR_BATCH_EMPTY`; and the batch's brokerage must hold a licence of `license_type` `SURPLUS_LINES` whose `state_code` equals the batch state's `state_code` and whose computed `status` is `ACTIVE`, else `ERR_BROKER_LICENSE_NOT_ACTIVE`. On success every `BATCHED` line of the batch moves to `FILED`, the batch's `status` becomes `SUBMITTED`, and the batch's `version` increments. Each policy touched by the batch then advances its tax dimension to `FILED` once all of that policy's lines are `FILED`, `VOIDED` or `REMITTED`, incrementing that policy's `version` — reached as `CALCULATED → FILED` when at least one of the policy's lines was swept into this batch and the policy had never been adjusted, and as `ADJUSTED → FILED` when the policy had been adjusted and every one of its lines now stands at `FILED` or `VOIDED`.

**Remittance** advances `SUBMITTED → REMITTED`, which is terminal, and carries a single field: `remitted_amount_cents`. Two preconditions apply, and both belong to the segregation-and-money rungs of the ladder: the acting `X-User-ID` must differ from the batch's `prepared_by_user_id`, else `ERR_SEGREGATION_OF_DUTIES`; and `remitted_amount_cents` must equal the batch's computed `total_due_cents` exactly, else `ERR_REMITTANCE_AMOUNT_MISMATCH` — including when that total is negative. On success every `FILED` line of the batch moves to `REMITTED`, the acting `X-User-ID` is recorded as `remitted_by_user_id`, the batch's `status` becomes `REMITTED`, and the batch's `version` increments. Each policy touched by the batch then advances its tax dimension `FILED → REMITTED` once all of that policy's lines are `REMITTED` or `VOIDED`, incrementing that policy's `version`.

## 4. Endpoint Definitions

Operations that create a new stand-alone resource, or that add a new distinct resource to a collection, return `201 Created`. Operations that modify an existing resource — including every state transition and every partial amendment — return `200 OK`. Read operations return `200 OK`. Every endpoint requires the `X-User-ID` and `X-User-Role` headers described in §2.1, and every list endpoint additionally accepts the `limit` and `offset` query parameters described in §2.3.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| POST | `/_clock/set_current_utc` | Set the server's logical clock; every time-dependent rule reads this clock. | Any |
| POST | `/brokers` | Register a surplus lines brokerage. | PlatformAdmin |
| GET | `/brokers/{id}` | Retrieve a brokerage. | Any |
| POST | `/brokers/{id}/suspend` | Suspend a brokerage. | PlatformAdmin |
| POST | `/brokers/{id}/licenses` | Record a state licence held by the brokerage. | PlatformAdmin |
| GET | `/brokers/{id}/licenses` | List the licences held by a brokerage. | Any |
| POST | `/state-programs` | Configure a state's surplus lines program. | PlatformAdmin |
| GET | `/state-programs/{id}` | Retrieve a state program. | Any |
| PATCH | `/state-programs/{id}` | Amend a state program's rates, thresholds or calendar. | PlatformAdmin |
| POST | `/carriers` | Register a non-admitted insurer. | PlatformAdmin |
| GET | `/carriers/{id}` | Retrieve an insurer. | Any |
| PATCH | `/carriers/{id}` | Amend an insurer's financial profile. | PlatformAdmin |
| POST | `/carrier-eligibilities` | Add an insurer to a state's eligible surplus lines white list. | StateRegulator |
| GET | `/carrier-eligibilities/{id}` | Retrieve a white-list entry. | Any |
| GET | `/carrier-eligibilities` | List white-list entries. | Any |
| POST | `/carrier-eligibilities/{id}/remove` | Remove an insurer from a state's white list. | StateRegulator |
| POST | `/carriers/{id}/security-reviews` | Open a market security review of an insurer. | ComplianceOfficer |
| GET | `/carriers/{id}/security-reviews` | List the market security reviews of an insurer. | Any |
| POST | `/market-security-reviews/{id}/start` | Begin the review and compute its score. | ComplianceOfficer |
| POST | `/market-security-reviews/{id}/decide` | Record the compliance decision. | ComplianceOfficer |
| POST | `/placements` | Open a placement file for a risk and determine its home state. | PlacementBroker |
| GET | `/placements/{id}` | Retrieve a placement. | Any |
| GET | `/placements` | List placements. | Any |
| POST | `/placements/{id}/begin-search` | Begin, or re-begin after a change request, the diligent search. | PlacementBroker |
| POST | `/placements/{id}/complete-search` | Assert that the diligent search is complete. | PlacementBroker |
| POST | `/placements/{id}/request-changes` | Send a completed search back to the broker for revision. | ComplianceOfficer |
| POST | `/placements/{id}/declinations` | Record a declination received from an admitted carrier. | PlacementBroker |
| GET | `/placements/{id}/declinations` | List the declinations recorded against a placement. | Any |
| POST | `/declinations/{id}/invalidate` | Strike a declination from the diligent search record. | ComplianceOfficer |
| POST | `/policies` | Issue a surplus lines policy against a completed placement. | PlacementBroker |
| GET | `/policies/{id}` | Retrieve a policy. | Any |
| GET | `/policies` | List policies. | Any |
| POST | `/policies/{id}/affix-notices` | Record that the state's required surplus lines notices have been affixed. | PlacementBroker |
| POST | `/policies/{id}/calculate-tax` | Compute the taxable premium, state allocation, premium tax and stamping fee. | TaxFiler |
| POST | `/policies/{id}/submit-stamping` | Submit the policy to the home state's stamping office. | TaxFiler |
| POST | `/policies/{id}/stamping-decision` | Record the stamping office's decision. | StateRegulator |
| GET | `/policies/{id}/allocations` | List the policy's per-state premium allocation rows. | Any |
| POST | `/policies/{id}/endorsements` | Draft an endorsement to the policy. | PlacementBroker |
| GET | `/endorsements/{id}` | Retrieve an endorsement. | Any |
| GET | `/endorsements` | List endorsements. | Any |
| POST | `/endorsements/{id}/issue` | Issue the endorsement and cascade the premium and tax recomputation. | PlacementBroker |
| POST | `/endorsements/{id}/void` | Void an endorsement. | PlacementBroker |
| POST | `/policies/{id}/cancellations` | Request cancellation of the policy. | PlacementBroker |
| GET | `/policies/{id}/cancellations` | List the cancellation requests raised against a policy. | Any |
| POST | `/cancellations/{id}/process` | Process the cancellation and compute the return premium and refunds. | PlacementBroker |
| GET | `/tax-filing-lines/{id}` | Retrieve a single premium tax filing line. | Any |
| GET | `/tax-filing-lines` | List premium tax filing lines. | Any |
| POST | `/filing-batches` | Open a premium tax filing batch for one state, brokerage and period. | TaxFiler |
| GET | `/filing-batches/{id}` | Retrieve a filing batch. | Any |
| GET | `/filing-batches` | List filing batches. | Any |
| POST | `/filing-batches/{id}/prepare` | Sweep open filing lines into the batch, total them and apply any penalty. | TaxFiler |
| POST | `/filing-batches/{id}/submit` | File the batch with the state. | TaxFiler |
| POST | `/filing-batches/{id}/remit` | Remit the amount due. | TaxFiler |
| POST | `/policies/{id}/affidavits` | Draft a broker affidavit against the policy. | PlacementBroker |
| GET | `/policies/{id}/affidavits` | List the affidavits drafted against a policy. | Any |
| POST | `/affidavits/{id}/sign` | Sign the affidavit. | PlacementBroker, ComplianceOfficer |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| --- | --- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_NOT_RESOURCE_OWNER` | 403 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_BROKER_NOT_FOUND` | 404 |
| `ERR_STATE_PROGRAM_NOT_FOUND` | 404 |
| `ERR_CARRIER_NOT_FOUND` | 404 |
| `ERR_CARRIER_ELIGIBILITY_NOT_FOUND` | 404 |
| `ERR_MARKET_SECURITY_REVIEW_NOT_FOUND` | 404 |
| `ERR_PLACEMENT_NOT_FOUND` | 404 |
| `ERR_DECLINATION_NOT_FOUND` | 404 |
| `ERR_POLICY_NOT_FOUND` | 404 |
| `ERR_ENDORSEMENT_NOT_FOUND` | 404 |
| `ERR_CANCELLATION_NOT_FOUND` | 404 |
| `ERR_TAX_FILING_LINE_NOT_FOUND` | 404 |
| `ERR_FILING_BATCH_NOT_FOUND` | 404 |
| `ERR_AFFIDAVIT_NOT_FOUND` | 404 |
| `ERR_STALE_PLACEMENT_VERSION` | 412 |
| `ERR_STALE_POLICY_VERSION` | 412 |
| `ERR_STALE_CARRIER_VERSION` | 412 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_PLACEMENT_NOT_BINDABLE` | 409 |
| `ERR_PLACEMENT_ALREADY_BOUND` | 409 |
| `ERR_POLICY_NOT_ISSUED` | 409 |
| `ERR_TAX_NOT_CALCULATED` | 409 |
| `ERR_NOTICES_NOT_AFFIXED` | 409 |
| `ERR_REVIEW_ALREADY_OPEN` | 409 |
| `ERR_BROKER_SUSPENDED` | 409 |
| `ERR_BATCH_EMPTY` | 409 |
| `ERR_ENDORSEMENT_ALREADY_REMITTED` | 409 |
| `ERR_SEGREGATION_OF_DUTIES` | 409 |
| `ERR_BROKER_LICENSE_NOT_ACTIVE` | 409 |
| `ERR_CARRIER_NOT_SECURITY_APPROVED` | 409 |
| `ERR_CARRIER_NOT_WHITE_LISTED` | 409 |
| `ERR_CARRIER_BELOW_STATE_CAPITAL_MINIMUM` | 409 |
| `ERR_POLICY_TERM_OVERLAP` | 409 |
| `ERR_ELIGIBILITY_WINDOW_CONFLICT` | 409 |
| `ERR_STATE_PROGRAM_DUPLICATE` | 409 |
| `ERR_CARRIER_DUPLICATE` | 409 |
| `ERR_HOME_STATE_INDETERMINATE` | 422 |
| `ERR_DILIGENT_SEARCH_INSUFFICIENT` | 422 |
| `ERR_ALLOCATION_STATE_PROGRAM_MISSING` | 422 |
| `ERR_NOTICES_INCOMPLETE` | 422 |
| `ERR_AFFIDAVIT_COUNT_MISMATCH` | 422 |
| `ERR_DECISION_SCORE_MISMATCH` | 422 |
| `ERR_CONDITIONS_NOTE_REQUIRED` | 422 |
| `ERR_REJECTION_REASON_REQUIRED` | 422 |
| `ERR_SUPERSEDE_TARGET_INVALID` | 422 |
| `ERR_PREMIUM_WOULD_BE_NON_POSITIVE` | 422 |
| `ERR_CANCELLATION_DATE_OUT_OF_TERM` | 422 |
| `ERR_FLAT_CANCELLATION_NOT_AVAILABLE` | 422 |
| `ERR_PERIOD_KEY_MALFORMED` | 422 |
| `ERR_REMITTANCE_AMOUNT_MISMATCH` | 422 |
