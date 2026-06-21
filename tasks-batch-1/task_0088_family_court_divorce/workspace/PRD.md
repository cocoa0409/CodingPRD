# Family Court Divorce API — Product Requirements Document

## 1. Introduction

This document specifies the Family Court Divorce API, a workflow-orchestration system that carries a dissolution-of-marriage matter from its first filing through to a final judgment of the court. A divorce case is rarely a single transaction; it is a sequence of contested and uncontested steps — a petition is filed and served, the opposing spouse answers or defaults, both spouses disclose their finances, the parents negotiate a parenting plan, a neutral mediator runs settlement sessions, support obligations are computed against the governing state guideline, and eventually a judge enters either temporary relief or a final judgment. The API models each of these steps as a first-class resource with its own lifecycle, and it enforces the procedural ordering, the financial mathematics, and the ethical guardrails that family courts depend upon.

Two concerns dominate the design. First, **money must reconcile**: child- and spousal-support amounts are never supplied by a client — they are derived server-side from a published state guideline schedule, and a case carries a conserved ledger that always equals the sum of its currently active obligations. Second, **roles must stay separated**: a judicial officer who mediated a case may never be the same officer who enters its final judgment, and the petitioning spouse and responding spouse are non-overlapping owners of their own resources. The sections that follow define the global contract (Section 2), the business workflows and the calculations that drive them (Section 3), the endpoint surface (Section 4), and the catalogue of error identifiers (Section 5).

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and conventions that apply across every endpoint.

### 2.1. User and Role-Based Access Control

Every request must be authenticated through two mandatory HTTP headers: `X-User-ID`, which identifies the acting operator, and `X-User-Role`, which declares the capacity in which they act. If either header is missing, or the role is not one of the recognized roles, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). The system recognizes exactly five roles: `Clerk`, `Judge`, `Mediator`, `Petitioner`, and `Respondent`. When a request is authenticated but the acting role is not permitted to perform the requested operation — or an ownership-bound role acts on a resource it does not own — the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403).

The five roles divide into two identity models. The `Clerk`, `Judge`, and `Mediator` roles are **opaque operator identities**: when `X-User-Role` is `Clerk`, `Judge`, or `Mediator`, the `X-User-ID` is an opaque operator identifier that is not tied to any persisted entity's `id`. The server may record such an identifier on a case — for example, it writes the acting mediator's identifier into `mediator_user_id` when a case enters mediation, and the acting judge's identifier into `judge_user_id` when judgment is entered — but it never compares these identifiers to any entity's `id`. The two officer roles are further constrained by segregation of duties, described in Section 2.4.

The `Petitioner` and `Respondent` roles are **entity-backed identities** tied to the `Party` entity. When `X-User-Role` is `Petitioner`, `X-User-ID` is the operator identifier bound to a petitioning `Party` — that is, the `Party` whose `role` is `PETITIONER` and whose `user_id` equals `X-User-ID`; ownership checks on any resource that references that `Party` compare the resource's party foreign key to `X-User-ID` via the owning `Party`'s `user_id`. Likewise, when `X-User-Role` is `Respondent`, `X-User-ID` is the operator identifier bound to the responding `Party` (the `Party` whose `role` is `RESPONDENT` and whose `user_id` equals `X-User-ID`), and ownership of party-bound resources is determined the same way. A petitioner and a respondent are peers: neither may act on the other's disclosures or pleadings.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies how many items to skip and defaults to 0, with a minimum of 0. A `limit` outside the inclusive range of 1 through 100, or a negative `offset`, is rejected with `ERR_PAGINATION_INVALID` (HTTP 422).

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp in ascending order. Every list response includes the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties, Versioning, and Identifier Resolution

Most resources in the system — `Case`, `Party`, `Child`, `Pleading`, `FinancialDisclosure`, `ParentingPlan`, `MediationSession`, `SupportOrder`, `CourtOrder`, and `Hearing` — carry a standard set of system-managed fields: an `id` (a server-minted UUID with no type prefix), a `created_at` timestamp (ISO 8601 UTC with three fractional digits) recording when the resource was first created, an `updated_at` timestamp (same format) recording the most recent mutation, and an integer `version` that begins at 1 and increments by one with every mutation to the resource. The `GuidelineSchedule` entity is configuration data and is immutable after creation; it therefore carries only `id` and `created_at` — it has neither an `updated_at` field nor a `version` field.

Whenever a derived or system field changes — for example when a case's computed ledger fields are recomputed — that counts as a mutation of the owning resource: its `updated_at` is refreshed and its `version` increments. References are resolved left to right. For any request, the system first validates each path identifier and each foreign-key field present in the request body against the existing resources, in the order they appear; the first identifier that does not resolve to an existing resource causes the request to be rejected with `ERR_NOT_FOUND` (HTTP 404) before any business rule is evaluated.

### 2.5. Validation Ordering and the Error Precedence Ladder

When several checks could fail on the same request, they are evaluated in a fixed precedence order, and the first failure determines the response. Authentication comes first: a missing or unrecognized header pair yields `ERR_UNAUTHENTICATED` (HTTP 401). Next is role authorization — an operation attempted by a disallowed role, or by an ownership-bound role acting on a resource it does not own, yields `ERR_FORBIDDEN_ROLE` (HTTP 403). Third, every path identifier and body foreign key must resolve to an existing resource, failing which the response is `ERR_NOT_FOUND` (HTTP 404). Fourth, the request body is checked for schema conformance — required fields present, enumerations valid, and numeric ranges respected — failing which the response is `ERR_INVALID_REQUEST` (HTTP 422). Fifth, for any state-transition operation, the target resource must currently be in a state from which the requested transition is defined; otherwise the response is `ERR_INVALID_STATE` (HTTP 409). Only after these five gates pass does the system evaluate the operation-specific business rules described in Section 3, in which referential-state checks, segregation-of-duties checks, temporal-overlap checks, and optimistic-concurrency checks each have their own dedicated identifiers. Cross-entity referential-state checks apply on three operations in particular — serving an answer pleading, entering a court order, and concluding a mediation session — and where such a check fails without a more specific identifier, the generic referential-state failure is reported as `ERR_REFERENCED_STATE_INVALID` (HTTP 409); the more specific referential failures on those operations (`ERR_PETITION_NOT_SERVED`, `ERR_PLAN_NOT_AGREED`, `ERR_SUPPORT_ORDER_NOT_CALCULATED`, and `ERR_DISCLOSURES_NOT_VERIFIED`) are described with their workflows in Section 3.

Pagination validation for list endpoints is treated as a body/parameter validation concern and surfaces as `ERR_PAGINATION_INVALID`. The guideline-existence check that gates case creation (described in Section 3.1) is a referential check that surfaces as `ERR_GUIDELINE_NOT_FOUND` rather than a generic not-found.

### 2.6. Optimistic Concurrency on Final Judgment

Entering a final judgment is the only operation that participates in optimistic concurrency control, because it is the operation that can be silently invalidated by a competing writer. When a judge enters a `FINAL_JUDGMENT` order, the request must carry an `expected_case_version` field whose value is the `version` of the target `Case` that the client last observed. If `expected_case_version` does not equal the case's current `version`, the entry is rejected with `ERR_STALE_CASE_VERSION` (HTTP 412). This captures the situation where another writer has already entered a final judgment on the same case — which legitimately advances the case to `JUDGMENT_ENTERED` and bumps its `version` — so the current writer's view of the case is stale and its judgment must not be allowed to land on top. No other endpoint accepts or requires a version field; only final-judgment entry is version-checked, and entering a `TEMPORARY` order is not.

### 2.7. Segregation of Duties

Family-court ethics require that the neutral who facilitated settlement not also be the adjudicator. The system enforces this as a hard rule at the moment a final judgment is entered: the acting judge's `X-User-ID` must differ from the case's recorded `mediator_user_id`. If they are the same operator, entry of the `FINAL_JUDGMENT` is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403). This check is not performed when a mediator is assigned to a case — assigning a mediator merely records `mediator_user_id` — and it is not performed when a `TEMPORARY` order is entered; it applies solely to final-judgment entry.

### 2.8. Support Mathematics: Currency, Precision, and the Conserved Ledger

All monetary amounts in the system are expressed as whole integer cents, and all support computations operate on integer cents. Where a calculation step requires rounding (described per formula in Section 3), the system rounds half up. The net-disposable-income computation involves no fractional rounding at all because its inputs are already whole cents; child-support and spousal-support computations round half up to whole cents at each pinned step, and the parenting-time fraction is the one exception that is carried to four decimal places (also rounded half up).

Each case maintains two conserved ledger fields that are never supplied by a client. The `active_support_total_cents` field is the sum of `monthly_amount_cents` across every `SupportOrder` belonging to the case whose `status` is `ACTIVE`; it is recomputed on every support-order status change so that it always reflects the live set of active obligations. The `net_fees_collected_cents` field equals the case's `filing_fee_cents` while the case has not been dismissed, and becomes 0 once the case is dismissed, modeling the refund of the filing fee on dismissal. A case also exposes two computed boolean flags, `petitioner_disclosure_verified` and `respondent_disclosure_verified`, each true exactly when the corresponding party's `FinancialDisclosure` has reached `VERIFIED` status.

### 2.9. Hierarchical Consistency and Cascades

The system's consistency model is immediate: every cascade and every derived-field recomputation completes within the request that triggers it, and the response reflects the post-cascade state. Several operations mutate more than one entity, and in every such case the secondary effects are part of the operation's contract, not an afterthought. Concluding a mediation session in full agreement cascades through the parenting plan, the child-support orders, and the case status; entering a final judgment that supersedes a temporary order cascades through that temporary order and its non-shared support obligations; dismissing a case compensates by refunding fees and vacating support orders. Each entity that a cascade mutates has its own `updated_at` refreshed and its own `version` incremented, and the case ledger fields are recomputed wherever a support order changes status. The detailed mechanics live with the workflows in Section 3.

## 3. Business Logic & Workflows

### 3.1. Opening a Case and Registering Guidelines

Before any case can be opened for a given jurisdiction, a clerk must register that jurisdiction's support guideline through the guideline-registration capability. A guideline schedule is created with a two-letter, uppercase `state_code` that is unique among schedules, an ordered array of child-support tiers in `basic_obligation_tiers`, and four tuning parameters: `spousal_payor_pct` (the payor's share of net income for spousal support, which must be strictly greater than 0 and strictly less than 1, defaulting to 0.40 when omitted), `spousal_payee_offset_pct` (the payee's offset share, same open range, defaulting to 0.50), `shared_custody_threshold_pct` (the parenting-time fraction at or above which the shared-custody child-support offset applies, same open range, defaulting to 0.40), and `long_marriage_months` (the marriage duration in months at or above which spousal support becomes indefinite, which must be at least 0, defaulting to 120). Each entry of `basic_obligation_tiers` is an object describing a contiguous income band that ascends by its lower bound; each tier carries a `min_combined_monthly_cents` lower bound, a `max_combined_monthly_cents` upper bound, a `base_cents_one_child` base obligation for a single child, and a `marginal_pct_per_extra_child` marginal rate for each additional child. Guideline schedules are immutable configuration once registered.

A clerk opens a divorce matter by supplying a `state_code`, a `caption` (the case title, such as "In re Marriage of Smith"), a `marriage_months` count (the marriage's duration in months at filing, which must be at least 0), and a `filing_fee_cents` amount (which must be at least 0). The `state_code` must match the `state_code` of an existing registered guideline schedule; if no such schedule exists, case creation is rejected with `ERR_GUIDELINE_NOT_FOUND`. A newly opened case enters `FILED` status with `version` 1, its `net_fees_collected_cents` initialized to the supplied `filing_fee_cents`, and its `active_support_total_cents` initialized to 0. The case's `status`, `mediator_user_id`, `judge_user_id`, and the computed ledger and disclosure-flag fields are all system-owned and never client-supplied; `mediator_user_id` and `judge_user_id` are null until a mediator is assigned and a judgment is entered, respectively.

Once a case has reached a terminal status — either `JUDGMENT_ENTERED` or `DISMISSED` — it is frozen. Any further mutation of the case, and any attempt to create a child resource (a party, child, pleading, financial disclosure, parenting plan, support order, court order, mediation session, or hearing) under such a case, as well as any of the case status-driving actions (administrative advance, default, dismiss, or assign-mediator), is rejected with `ERR_CASE_TERMINAL` (HTTP 409).

### 3.2. Parties, Children, and the Pleading Cycle

A clerk adds the spouses to a case as `Party` records. Each party is created with the `case_id` it belongs to, a `role` of either `PETITIONER` or `RESPONDENT`, the operator `user_id` the party is bound to (the petitioner or respondent role acts as this party only when `X-User-ID` equals this `user_id`), a `full_name`, and a declared `gross_monthly_income_cents` (the income figure used by the temporary support variant, which must be at least 0). A case may hold exactly one petitioner and at most one respondent; attempting to add a second party in a role already present on the case is rejected with `ERR_DUPLICATE_PARTY_ROLE`. A clerk likewise records each subject child as a `Child` record carrying its `case_id`, `full_name`, and `birth_year` (informational, and at least 1900).

The procedural spine of a case is the pleading cycle. A pleading is filed with its `case_id`, a `pleading_type` of either `PETITION` or `ANSWER`, and the `filed_by_party_id` identifying the party who filed it. A case may have exactly one petition; a second petition is rejected with `ERR_DUPLICATE_PETITION`. Pleadings begin in `DRAFT` status. Serving a pleading advances it from `DRAFT` to `SERVED`, stamping its `served_at` with the request timestamp. An answer may only be served after the case's petition has already been served; attempting to serve an answer while the petition is not yet served is rejected with `ERR_PETITION_NOT_SERVED`.

Serving the petition drives the case from `FILED` to `AWAITING_RESPONSE` and increments the case `version`. From `AWAITING_RESPONSE` the case forks two ways. If the respondent files an answer (which must be filed by the respondent party) and that answer is served, the case advances from `AWAITING_RESPONSE` to `CONTESTED`, the case `version` increments, and as a system side effect the original petition transitions from `SERVED` to `ANSWERED` (the answer itself remains `SERVED`, which is terminal for it). Alternatively, if no answer pleading exists for the case, a clerk may default the respondent, moving the case from `AWAITING_RESPONSE` to `DEFAULT_PENDING` and incrementing the case `version`; if an answer pleading does exist, the default attempt is rejected with `ERR_ANSWER_EXISTS`. A clerk may dismiss a case from any pre-judgment status (`FILED`, `AWAITING_RESPONSE`, `DEFAULT_PENDING`, `CONTESTED`, `DISCOVERY`, `MEDIATION`, or `AWAITING_JUDGMENT`), which moves the case `status` to `DISMISSED`; the compensating effects of dismissal are detailed in Section 3.8.

### 3.3. Financial Disclosure and Net Income

Each spouse must disclose their finances. A financial disclosure is created against a `party_id` (the disclosing party) and carries a denormalized `case_id` for case-scoped queries, a verified `gross_monthly_income_cents` (used by the final support variant, at least 0), and three monthly deduction lines: `tax_withholding_cents` (income tax plus payroll withholding), `mandatory_retirement_cents` (mandatory retirement contributions), and `health_insurance_cents` (the health-insurance premium), each at least 0. A disclosure begins in `DRAFT` status; its `net_monthly_income_cents` is a computed field that is null until the disclosure is submitted.

Submitting a disclosure advances it from `DRAFT` to `SUBMITTED`. The acting party must own the disclosure — the `X-User-ID` must equal the `user_id` of the `Party` named by `party_id` — otherwise the submission is forbidden. At submission, the system computes net disposable income: it first sums the three deduction lines `tax_withholding_cents`, `mandatory_retirement_cents`, and `health_insurance_cents` in that field order, then subtracts that total from `gross_monthly_income_cents`, then floors the result at 0 cents, storing the outcome in `net_monthly_income_cents`. Because all inputs are whole cents, no fractional rounding occurs and the result is fully deterministic. If the gross income is less than the sum of the three declared deductions — that is, if net income would be negative — the submission is rejected with `ERR_NEGATIVE_NET_INCOME` (HTTP 422); equivalently, submission requires that gross income be at least the sum of the three deductions.

A clerk reviews each submitted disclosure. Verifying a disclosure advances it from `SUBMITTED` to `VERIFIED`, but only while the owning case is in one of `DISCOVERY`, `MEDIATION`, `DEFAULT_PENDING`, or `AWAITING_JUDGMENT`; on verification the system recomputes the owning case's `petitioner_disclosure_verified` and `respondent_disclosure_verified` flags. Alternatively a clerk may return a submitted disclosure for correction, moving it from `SUBMITTED` to `RETURNED`. A returned disclosure may be resubmitted: submitting it again advances it from `RETURNED` back to `SUBMITTED`, re-deriving `net_monthly_income_cents` from its current field values (so a resubmission with edited deductions yields a new net), subject to the same ownership check and the same non-negative-net requirement as the first submission. This resubmission loop may repeat.

### 3.4. The Parenting Plan and Its Revision Loop

A case has at most one parenting plan; proposing a second plan on a case is rejected with `ERR_DUPLICATE_PLAN`. Either spouse may propose the plan by supplying the `case_id`, the `proposed_by_party_id` (the party proposing this version), and the overnight allocation: `petitioner_overnights` (annual overnights for the petitioner, between 0 and 365 inclusive) and `respondent_overnights` (annual overnights for the respondent). The two overnight counts are a conserved quantity: `petitioner_overnights` plus `respondent_overnights` must total exactly 365, and any proposal or revision that violates this is rejected with `ERR_OVERNIGHTS_NOT_365` (HTTP 422). On creation and on every revision, the system computes `petitioner_time_pct` as the petitioner's overnights divided by 365, rounded half up to four decimal places; the respondent's fraction is the complement, one minus `petitioner_time_pct`. A newly proposed plan enters `PROPOSED` status.

The plan moves through a negotiation that may cycle. A plan may be disputed or agreed by the case party who did *not* propose the current version — the acting party's identity must differ from `proposed_by_party_id`; if the acting party is the proposer, the action is rejected with `ERR_NOT_DISPUTING_PARTY` (HTTP 403). Disputing a plan advances it from `PROPOSED` to `DISPUTED`. From `DISPUTED`, the disputing side may revise the overnights: a revision supplies new `petitioner_overnights` and `respondent_overnights` (which must still total 365), updates those overnight values, reassigns `proposed_by_party_id` to the acting party, recomputes `petitioner_time_pct`, and moves the plan from `DISPUTED` to `REVISED`. A revised plan may itself be disputed again by the other party (the one who did not propose the revision), moving it from `REVISED` back to `DISPUTED` — this is the revision loop, and it may repeat across rounds. At any point a non-proposing party may agree: agreeing advances the plan from `PROPOSED` to `AGREED`, or from `REVISED` to `AGREED`. The terminal step, `AGREED` to `ADOPTED`, is not a client action — it is a system cascade driven by mediation, described in Section 3.5.

### 3.5. Mediation and the Full-Agreement Cascade

Once a case reaches `DISCOVERY` and both spouses have disclosed, a clerk assigns a mediator. Assigning a mediator records the supplied `mediator_user_id` onto the case, moves the case from `DISCOVERY` to `MEDIATION`, and increments the case `version`. Assignment is permitted only when both parties' financial disclosures are in `SUBMITTED` or `VERIFIED` status; segregation of duties is not checked at assignment time. (The clerk-driven advance that takes a contested case from `CONTESTED` to `DISCOVERY` requires that both the petitioner and respondent parties exist on the case.)

A mediation session is scheduled with its `case_id`, the `mediator_user_id` running it (which must equal the case's recorded `mediator_user_id`), a `scheduled_start`, and a `scheduled_end` (ISO 8601 UTC, with the end after the start). On creation the session is assigned a `round_no` equal to one plus the count of prior sessions on the case that have reached `FULL_AGREEMENT`, `PARTIAL_AGREEMENT`, or `IMPASSE`, and enters `SCHEDULED` status. A new session must not collide with an existing non-terminal session of the *same* mediator: the booking interval is treated as a **closed** interval `[scheduled_start, scheduled_end]`, so two sessions that merely touch at an endpoint (a gap of zero) are still considered a conflict — a mandatory clearance buffer means adjacent sessions collide. A colliding session is rejected with `ERR_MEDIATOR_DOUBLE_BOOKED` (HTTP 409).

A mediator starts a session, advancing it from `SCHEDULED` to `IN_SESSION`; starting requires that the acting mediator's `X-User-ID` equal the case's `mediator_user_id` and that the case be in `MEDIATION`. A session in `IN_SESSION` is concluded with an `outcome`. An outcome of `PARTIAL_AGREEMENT` moves the session from `IN_SESSION` to `PARTIAL_AGREEMENT`, which is non-terminal — the same session row may be reopened for a further round, advancing it from `PARTIAL_AGREEMENT` back to `IN_SESSION` (the acting mediator must again match the case's `mediator_user_id`). An outcome of `IMPASSE` moves the session from `IN_SESSION` to `IMPASSE`, a terminal outcome. An outcome of `FULL_AGREEMENT` moves the session from `IN_SESSION` to `FULL_AGREEMENT`, but only if the case's parenting plan is currently in `AGREED` status; if the plan is not agreed, the conclusion is rejected with `ERR_PLAN_NOT_AGREED`.

Concluding in `FULL_AGREEMENT` triggers a three-hop cascade that completes within the same request. First, the case's parenting plan advances from `AGREED` to `ADOPTED`. Second, adoption of the plan triggers recomputation of the monthly amount of every `FINAL`-variant child-support order on the case (the final child-support math reads the now-adopted plan's time fraction). Third, the case advances from `MEDIATION` to `AWAITING_JUDGMENT` and its `version` increments; reaching `AWAITING_JUDGMENT` by way of mediation requires that the parenting plan be `ADOPTED`, and an attempt to reach it via mediation without an adopted plan is blocked with `ERR_PLAN_NOT_ADOPTED`.

### 3.6. Computing Support Obligations

Support orders are computed, never quoted. A clerk creates a support order by supplying the `case_id`, a `support_type` of either `CHILD` or `SPOUSAL`, the `payor_party_id` (the obligor) and `payee_party_id` (the recipient), and a `variant` of either `TEMPORARY` or `FINAL`. The server computes the order's `monthly_amount_cents` and `support_term_months`; these are never client-supplied. Creating any support order requires that both a petitioner and a respondent party exist on the case; if the respondent is missing, the request is rejected with `ERR_NO_RESPONDENT`. If the requested `variant` is `FINAL`, the relevant party's `FinancialDisclosure` must be `VERIFIED`; otherwise the request is rejected with `ERR_INCOME_NOT_AVAILABLE`. The support computation must match the requested `support_type` — invoking the child math for a spousal order or vice versa is rejected with `ERR_SUPPORT_TYPE_MISMATCH`. A newly created order enters `CALCULATED` status and counts toward the case ledger only once it becomes `ACTIVE`.

**Child support.** When `support_type` is `CHILD`, the obligation depends on three inputs: the combined monthly income, the number of children, and the payor's parenting-time fraction. The child count is the number of `Child` rows on the case. If there are no children, the `monthly_amount_cents` is 0 and computation stops. Otherwise the system first determines the combined monthly income. Under the `TEMPORARY` variant, the combined income is the sum of both parties' declared `gross_monthly_income_cents` (taken from the `Party` records), and the parenting-time offset uses the plan's current overnight split (often the proposed, not-yet-adopted split). Under the `FINAL` variant, the combined income is the sum of both parties' verified `net_monthly_income_cents` (taken from their verified disclosures — net figures, not gross), and the offset uses the adopted plan's time fraction; the formula is identical but the result differs materially. The system then selects the guideline tier whose income band contains the combined income — the tier where `min_combined_monthly_cents` is less than or equal to the combined income and the combined income is less than or equal to `max_combined_monthly_cents`. Both band endpoints are inclusive, and a value equal to a tier's maximum belongs to that tier rather than the next (ties resolve to the lower tier). The base obligation is the tier's `base_cents_one_child`. If there is more than one child, the base is scaled up to the tier's `base_cents_one_child` multiplied by the quantity one plus `marginal_pct_per_extra_child` times the number of extra children (the child count minus one), rounded half up to whole cents. The obligation is then prorated by the payor's income share: the payor's income divided by the combined income, multiplied by the scaled base, rounded half up to whole cents. The payor is the lower-overnight parent. Finally, the shared-custody offset is applied: the payor's parenting-time fraction is `petitioner_time_pct` if the payor is the petitioner, or one minus `petitioner_time_pct` if the payor is the respondent; if that payor time fraction is at or above the schedule's `shared_custody_threshold_pct` (at or above, not strictly above), the obligation is reduced by multiplying it by the quantity one minus the payor's time fraction, again rounded half up to whole cents. The final `monthly_amount_cents` is the greater of 0 and the resulting obligation. A child support order's `support_term_months` is 0.

**Spousal support.** When `support_type` is `SPOUSAL`, the obligation is a threshold formula keyed on marriage duration. The gross obligation is the schedule's `spousal_payor_pct` multiplied by the payor's income, minus the schedule's `spousal_payee_offset_pct` multiplied by the payee's income, rounded half up to whole cents; the stored `monthly_amount_cents` is the greater of 0 and that gross obligation, so it is never negative. As with child support, the income inputs depend on the variant: under `TEMPORARY`, the payor and payee incomes are the declared gross `gross_monthly_income_cents` from the `Party` records; under `FINAL`, they are the verified `net_monthly_income_cents` from the parties' disclosures, which are net figures and therefore shrink the obligation relative to the temporary gross-based figure. The term is set from the marriage duration: if the case's `marriage_months` is at or above the schedule's `long_marriage_months` (at or above, not strictly above), the `support_term_months` is set to the sentinel 0, meaning an indefinite term; otherwise it is the floor of `marriage_months` divided by 2 — half the marriage length in whole months.

### 3.7. Court Orders: Temporary Relief and Final Judgment

A court order is drafted by a clerk or a judge with its `case_id`, an `order_kind` of either `TEMPORARY` or `FINAL_JUDGMENT`, an array of `support_order_ids` that the order governs, an optional `parenting_plan_id` (the governed parenting plan, required for a `FINAL_JUDGMENT`), and an optional `supersedes_order_id` that names a prior court order this one supersedes (used by a final judgment to supersede an earlier temporary order; null for a temporary order). Drafting checks only that the referenced identifiers exist and belong to the same case — it does not yet require the referenced support orders to be in any particular state. A drafted order enters `DRAFT` status.

Entering an order advances it from `DRAFT` to `ENTERED`, stamping `entered_at` with the request timestamp. At entry time, every referenced support order must be in `CALCULATED` status; if any referenced support order is not `CALCULATED`, entry is rejected with `ERR_SUPPORT_ORDER_NOT_CALCULATED`. On a successful entry, all referenced support orders advance to `ACTIVE` and the case's `active_support_total_cents` is recomputed to reflect the newly active obligations. A `TEMPORARY` order may be entered while the case is in `DISCOVERY`, `MEDIATION`, or `DEFAULT_PENDING`. A `FINAL_JUDGMENT` may be entered only while the case is in `AWAITING_JUDGMENT`, and entry of a final judgment carries three additional gates. First, the disclosures must be verified: both parties' financial disclosures must be `VERIFIED` (the case's `petitioner_disclosure_verified` and `respondent_disclosure_verified` flags both true), except on the default path, where the petitioner's disclosure being verified suffices; failing this, entry is rejected with `ERR_DISCLOSURES_NOT_VERIFIED`. Second, segregation of duties applies: the acting judge's `X-User-ID` must not equal the case's `mediator_user_id`, on pain of `ERR_SEGREGATION_OF_DUTIES`. Third, the optimistic-concurrency check applies: the request must carry an `expected_case_version` matching the case's current `version`, failing which entry is rejected with `ERR_STALE_CASE_VERSION`.

Entering a final judgment cascades. If the final judgment names a `supersedes_order_id`, that prior `TEMPORARY` court order advances from `ENTERED` to `SUPERSEDED` (only temporary orders may become superseded). When the temporary order is superseded, every support order it referenced that is *not* also referenced by the entering final judgment advances to `VACATED`, and the case's `active_support_total_cents` is recomputed — this is the compensating action that keeps the ledger conserved as obligations are replaced. Finally, entering the final judgment records the acting judge's `X-User-ID` into the case's `judge_user_id`, advances the case from `AWAITING_JUDGMENT` to `JUDGMENT_ENTERED`, and increments the case `version`. The case is now terminal.

### 3.8. Hearings, Dismissal, and Compensating Effects

Hearings are scheduled independently of the merits workflow. A clerk schedules a hearing with its `case_id`, a `courtroom_code` (the courtroom resource), a `scheduled_start`, and a `scheduled_end` (ISO 8601 UTC, end after start). A new hearing must not overlap an existing `SCHEDULED` hearing in the same `courtroom_code`; courtroom intervals are treated as **half-open** `[scheduled_start, scheduled_end)`, so back-to-back hearings where one's end exactly equals the next one's start are allowed, while any true overlap is rejected with `ERR_COURTROOM_DOUBLE_BOOKED` (HTTP 409). A scheduled hearing begins in `SCHEDULED` status. A judge marks a hearing held, advancing it from `SCHEDULED` to `HELD` (no clock comparison is enforced — only the status gate applies). A clerk may cancel a scheduled hearing, advancing it from `SCHEDULED` to `CANCELLED`.

Dismissal is the case's compensating exit. When a clerk dismisses a pre-judgment case, three things happen together within the request. The case `status` moves to `DISMISSED`. The case's `net_fees_collected_cents` is set to 0, modeling the refund of the filing fee. And every `SupportOrder` on the case that is not already `VACATED` is moved to `VACATED`, after which the case's `active_support_total_cents` is recomputed to 0. The case `version` increments. Like a final judgment, dismissal leaves the case terminal, so no further child resources or status actions are accepted on it.

The default path provides an alternate route to judgment that does not pass through mediation. From `DEFAULT_PENDING`, once the petitioner's financial disclosure is `VERIFIED`, a clerk advances the case to `AWAITING_JUDGMENT` (the administrative advance also covers the `CONTESTED`-to-`DISCOVERY` step, which requires both parties to exist, by accepting a `to_status` naming the target). A default judgment then proceeds on the petitioner's proof alone, which is why final-judgment entry on the default path requires only the petitioner's disclosure to be verified rather than both.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource return a `201 Created` status code. Operations that modify or transition an existing resource — including all of the action endpoints that drive state machines — return a `200 OK` status code. Read operations return `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/api/guideline-schedules` | Register a state's support guideline schedule (immutable config) | Clerk |
| GET | `/api/guideline-schedules/{id}` | Fetch a guideline schedule | Clerk, Judge, Mediator, Petitioner, Respondent |
| POST | `/api/cases` | Open a new divorce case | Clerk |
| GET | `/api/cases/{id}` | Fetch a case including computed ledger and disclosure flags | Clerk, Judge, Mediator, Petitioner, Respondent |
| GET | `/api/cases` | List cases (filter by `state_code` / `status`) | Clerk, Judge |
| POST | `/api/cases/{id}/default` | Move an unanswered case to `DEFAULT_PENDING` | Clerk |
| POST | `/api/cases/{id}/advance` | Clerk-driven status advance | Clerk |
| POST | `/api/cases/{id}/assign-mediator` | Assign a mediator and move to `MEDIATION` | Clerk |
| POST | `/api/cases/{id}/dismiss` | Dismiss a pre-judgment case | Clerk |
| POST | `/api/parties` | Add a party to a case | Clerk |
| GET | `/api/parties/{id}` | Fetch a party | Clerk, Judge, Mediator, Petitioner, Respondent |
| GET | `/api/parties` | List parties (filter by `case_id`) | Clerk, Judge, Mediator, Petitioner, Respondent |
| POST | `/api/children` | Add a subject child to a case | Clerk |
| GET | `/api/children/{id}` | Fetch a child | Clerk, Judge, Mediator, Petitioner, Respondent |
| GET | `/api/children` | List children (filter by `case_id`) | Clerk, Judge, Mediator, Petitioner, Respondent |
| POST | `/api/pleadings` | File a `PETITION` or `ANSWER` | Clerk, Petitioner, Respondent |
| GET | `/api/pleadings/{id}` | Fetch a pleading | Clerk, Judge, Mediator, Petitioner, Respondent |
| GET | `/api/pleadings` | List pleadings (filter by `case_id` and/or `filed_by_party_id`) | Clerk, Judge, Mediator, Petitioner, Respondent |
| POST | `/api/pleadings/{id}/serve` | Serve a pleading; drives case status | Clerk |
| POST | `/api/financial-disclosures` | Create a financial disclosure for a party | Clerk, Petitioner, Respondent |
| GET | `/api/financial-disclosures/{id}` | Fetch a financial disclosure | Clerk, Judge, Mediator, Petitioner, Respondent |
| GET | `/api/financial-disclosures` | List disclosures (filter by `party_id` and/or `case_id`) | Clerk, Judge, Mediator, Petitioner, Respondent |
| POST | `/api/financial-disclosures/{id}/submit` | Submit or resubmit a disclosure; computes net income | Petitioner, Respondent |
| POST | `/api/financial-disclosures/{id}/verify` | Verify a submitted disclosure | Clerk |
| POST | `/api/financial-disclosures/{id}/return` | Return a submitted disclosure for correction | Clerk |
| POST | `/api/parenting-plans` | Propose a parenting plan for a case | Petitioner, Respondent |
| GET | `/api/parenting-plans/{id}` | Fetch a parenting plan | Clerk, Judge, Mediator, Petitioner, Respondent |
| GET | `/api/parenting-plans` | List parenting plans (filter by `case_id` and/or `proposed_by_party_id`) | Clerk, Judge, Mediator, Petitioner, Respondent |
| POST | `/api/parenting-plans/{id}/dispute` | Dispute the current plan version | Petitioner, Respondent |
| POST | `/api/parenting-plans/{id}/revise` | Revise overnights on a disputed plan | Petitioner, Respondent |
| POST | `/api/parenting-plans/{id}/agree` | Agree to the current plan version | Petitioner, Respondent |
| POST | `/api/mediation-sessions` | Schedule a mediation session | Clerk, Mediator |
| GET | `/api/mediation-sessions/{id}` | Fetch a mediation session | Clerk, Judge, Mediator, Petitioner, Respondent |
| GET | `/api/mediation-sessions` | List mediation sessions (filter by `case_id`) | Clerk, Judge, Mediator, Petitioner, Respondent |
| POST | `/api/mediation-sessions/{id}/start` | Start or reopen a session | Mediator |
| POST | `/api/mediation-sessions/{id}/conclude` | Conclude a session with an outcome | Mediator |
| POST | `/api/support-orders` | Create a support order; amount computed server-side | Clerk |
| GET | `/api/support-orders/{id}` | Fetch a support order | Clerk, Judge, Mediator, Petitioner, Respondent |
| GET | `/api/support-orders` | List support orders (filter by `case_id`, `payor_party_id`, `payee_party_id`) | Clerk, Judge, Mediator, Petitioner, Respondent |
| POST | `/api/court-orders` | Draft a temporary order or final judgment | Clerk, Judge |
| GET | `/api/court-orders/{id}` | Fetch a court order | Clerk, Judge, Mediator, Petitioner, Respondent |
| GET | `/api/court-orders` | List court orders (filter by `case_id`, `parenting_plan_id`, `supersedes_order_id`) | Clerk, Judge, Mediator, Petitioner, Respondent |
| POST | `/api/court-orders/{id}/enter` | Enter an order; final judgment supersedes the temporary order | Judge |
| POST | `/api/hearings` | Schedule a hearing | Clerk |
| GET | `/api/hearings/{id}` | Fetch a hearing | Clerk, Judge, Mediator, Petitioner, Respondent |
| GET | `/api/hearings` | List hearings (filter by `case_id`) | Clerk, Judge, Mediator, Petitioner, Respondent |
| POST | `/api/hearings/{id}/hold` | Mark a hearing held | Judge |
| POST | `/api/hearings/{id}/cancel` | Cancel a hearing | Clerk |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN_ROLE` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 422 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_REFERENCED_STATE_INVALID` | 409 |
| `ERR_PETITION_NOT_SERVED` | 409 |
| `ERR_DISCLOSURES_NOT_VERIFIED` | 409 |
| `ERR_SUPPORT_ORDER_NOT_CALCULATED` | 409 |
| `ERR_PLAN_NOT_AGREED` | 409 |
| `ERR_PLAN_NOT_ADOPTED` | 409 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_STALE_CASE_VERSION` | 412 |
| `ERR_MEDIATOR_DOUBLE_BOOKED` | 409 |
| `ERR_COURTROOM_DOUBLE_BOOKED` | 409 |
| `ERR_OVERNIGHTS_NOT_365` | 422 |
| `ERR_NEGATIVE_NET_INCOME` | 422 |
| `ERR_DUPLICATE_PETITION` | 409 |
| `ERR_DUPLICATE_PARTY_ROLE` | 409 |
| `ERR_DUPLICATE_PLAN` | 409 |
| `ERR_NO_RESPONDENT` | 409 |
| `ERR_ANSWER_EXISTS` | 409 |
| `ERR_GUIDELINE_NOT_FOUND` | 404 |
| `ERR_INCOME_NOT_AVAILABLE` | 409 |
| `ERR_NOT_DISPUTING_PARTY` | 403 |
| `ERR_SUPPORT_TYPE_MISMATCH` | 422 |
| `ERR_PAGINATION_INVALID` | 422 |
| `ERR_CASE_TERMINAL` | 409 |
