# Vendor Security Assessment API — Product Requirements Document

## 1. Introduction

Third-party vendors sit behind a disproportionate share of security incidents: they hold regulated data, operate inside customer networks, and are too often reviewed once at onboarding and never again. The third-party security risk team needs a single system of record that carries a vendor from registration through tiered assessment, questionnaire scoring, independent evidence review, remediation, risk acceptance, contractual safeguards, continuous monitoring, and — eventually — provable offboarding, with every decision attributable and every deadline enforced by the platform rather than by spreadsheet discipline.

This document specifies the Vendor Security Assessment API. It governs how vendors are classified into assessment tiers from the sensitivity of the data they touch, the breadth of access they hold, and the business criticality they carry; how questionnaire responses are scored against pinned template versions; how SOC 2, ISO 27001, and penetration-test evidence is reviewed and converted into exception findings; how remediation plans and risk acceptances are decided under strict segregation of duties; how contract addenda are generated from tier and exception posture; how monitoring alerts pull reassessments forward; and how subprocessor disclosures and data-destruction attestations close the loop. All time-dependent behavior — response deadlines, acceptance expiries, offboarding deadlines, and reassessment cadences — is driven by a controllable logical clock so that scheduled transitions are deterministic and testable.

## 2. Global Specifications & System-Wide Principles

This section defines the platform-wide rules that apply to every endpoint in the API.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. The platform recognizes exactly four roles: `PlatformAdmin`, `RiskAnalyst`, `SecurityApprover`, and `VendorContact`. A request that is missing either header, or that declares a role outside this set, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is recognized but not permitted on the target endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403).

The identity carried by `X-User-ID` differs by role. When `X-User-Role` is `PlatformAdmin`, `RiskAnalyst`, or `SecurityApprover`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it — for example as `approved_by` on a remediation plan or `decided_by` on a risk acceptance or subprocessor disclosure — but never compares it to any entity's `id`. When `X-User-Role` is `VendorContact`, `X-User-ID` is the `id` of the acting `VendorContact` record; ownership checks on any resource that references a `VendorContact` compare the resource's foreign-key field to `X-User-ID`, and read access for a vendor-side caller is scoped to the vendor that owns the contact record — the contact's `vendor_id` determines which vendor's vendors, cycles, responses, evidence, exceptions, plans, addenda, disclosures, and attestations are visible.

Broadly: `PlatformAdmin` owns tier policies, monitoring-alert ingestion, and the logical clock. `RiskAnalyst` drives the assessment machinery — vendors, templates, cycle issuance and scoring, evidence review, exceptions, remediation, risk-acceptance requests, addendum drafting, alert handling, subprocessor review initiation, offboarding, and attestation verification. `SecurityApprover` holds the decision rights that must be segregated from the analyst: cycle approval and rejection, risk-acceptance decisions, subprocessor decisions, and addendum waivers. `VendorContact` is the vendor-side respondent — submitting questionnaire responses, evidence, remediation progress, subprocessor disclosures, addendum signatures, and offboarding attestations.

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

Endpoints that return lists of resources accept two query parameters. The `limit` parameter sets the maximum number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter sets how many items to skip and defaults to 0, and may never be negative. A `limit` or `offset` outside these bounds is rejected with `ERR_PAGINATION_INVALID` (HTTP 422). Unless otherwise stated, every list endpoint returns resources sorted by `created_at` in ascending order. The `meta` object of a list response carries `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties and Audit Fields

Every primary resource — Vendor, AssessmentTierPolicy, QuestionnaireTemplate, AssessmentCycle, QuestionnaireResponse, EvidenceArtifact, ExceptionFinding, RemediationPlan, RiskAcceptance, ContractAddendum, MonitoringAlert, SubprocessorDisclosure, and OffboardingAttestation — carries a standard set of system-managed fields:

- `id` (string): a unique, server-minted identifier formatted as a UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created.
- `updated_at` (string): an ISO 8601 UTC timestamp, refreshed on every modification of the resource.
- `version` (integer): a system-managed counter that starts on creation and increments by one on every mutation of the resource, including mutations the server applies as side effects of operations on related resources.

Two resources are exceptions to this rule: a `ReassessmentSchedule` event and a `VendorContact` carry only `id` and `created_at`. Both `updated_at` and `version` are absent on those two resources — they are append-only records and are never mutated after creation.

### 2.5. Nested Resource Retrieval

Most write endpoints and many read endpoints address a child resource through its parent chain — a cycle under a vendor, a response under a cycle, and so on. The platform resolves every path segment strictly left to right: the vendor first, then the cycle, then the child. The first identifier that does not correspond to an existing resource aborts the request with `ERR_NOT_FOUND` (HTTP 404) before any later segment — or any business rule — is evaluated. A request naming a valid child under the wrong parent is likewise a not-found failure, not a permission failure.

### 2.6. The Logical Clock and Scheduled State Transitions

All deadline and scheduling logic in the platform reads a single logical clock, never the host wall clock. At server startup the logical clock reads exactly `2026-08-01T00:00:00Z`; until it is explicitly set, every time-dependent rule evaluates against that instant. A `PlatformAdmin`-only test-driving capability advances the clock to a supplied `to_iso8601` instant and returns the resulting `current_utc`. Advancing the clock fires any auto-transitions that have become due — specifically the cycle expiry sweep and the risk-acceptance expiry sweep described in §3.3 and §3.6 — so clients can deterministically drive time-dependent behavior.

### 2.7. Optimistic Concurrency Control

Two write operations are guarded by optimistic concurrency control, and both require the guard field as a non-optional input.

Creating an assessment cycle requires `expected_vendor_version`, carrying the client's last-observed `version` of the target vendor. If the vendor's current `version` has advanced beyond that value — because another writer has since issued, closed, or otherwise mutated the vendor — the create is rejected with `ERR_STALE_VENDOR_VERSION` (HTTP 412), so the client cannot act on a vendor record it has not observed.

Approving a risk acceptance requires `expected_cycle_version`, carrying the approver's last-observed `version` of the parent cycle. If the cycle's `version` has advanced since — for example because a remediation verification or an exception closure changed the cycle's open-exception set — the approval is rejected with `ERR_STALE_CYCLE_VERSION` (HTTP 412), forcing the decision to be remade against the cycle as it actually stands.

`ERR_STALE_VERSION` (HTTP 422) is the reserved generic stale-write guard for any future OCC-guarded write that has no dedicated error identifier. Endpoints not named above do not take a version field at all.

### 2.8. Segregation of Duties

Decision points that carry audit weight are split across two hands. The acting user's `X-User-ID` must differ from the user who performed the prior gated step in five pairs: the approver of a risk acceptance must differ from its requester; the rejecter of a risk acceptance must likewise differ from its requester; the verifier of a remediation plan must differ from the analyst who accepted it (recorded as the plan's `approved_by`); the approver of a subprocessor disclosure must differ from the analyst who started its review; and the approver of an assessment cycle must differ from the analyst who completed the cycle's evidence review. Any attempt by one person to perform both halves of a gated pair is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 422).

### 2.9. Validation Order and Error Precedence

Every request is evaluated against one ordered validation cascade, and the first failing check determines the error returned — a request that fails an early check never surfaces a later one:

1. Authentication — `X-User-ID` and `X-User-Role` present and the role declared; failures yield `ERR_UNAUTHENTICATED` (401).
2. Authorization — the role must be permitted on the endpoint per §2.1; failures yield `ERR_FORBIDDEN` (403).
3. Path existence — path resources resolved left to right per §2.5; the first missing segment yields `ERR_NOT_FOUND` (404).
4. State permission — the target resource must be in a state that permits the requested transition; failures yield `ERR_INVALID_STATE` (409).
5. Segregation of duties — per §2.8; failures yield `ERR_SEGREGATION_OF_DUTIES` (422).
6. Optimistic concurrency — the OCC guards of §2.7; failures yield the guard's specific error, `ERR_STALE_VENDOR_VERSION` or `ERR_STALE_CYCLE_VERSION` (412).
7. Clock-dependent deadlines — response submission by `response_due_at`, attestation submission by `offboarding_deadline`, and a future `expires_at` on a new risk acceptance; violations yield `ERR_DEADLINE_PASSED` (422).
8. Schema and semantic completeness — at a single shared precedence tier: enum membership and required-field presence (an `item_key` known to the pinned template, a `destruction_method` whenever `data_destroyed` is true, a `severity` or `kind` inside its declared enum) yield `ERR_INVALID_REQUEST` (422), and the attestation-level semantic check — a submission asserting neither data return nor destruction — yields `ERR_ATTESTATION_INCOMPLETE` (422).
9. Uniqueness — at most one non-terminal cycle per vendor, reported as `ERR_CYCLE_ALREADY_ACTIVE` (409); at most one primary contact per vendor and at most one active tier policy, reported as `ERR_UNIQUENESS_VIOLATION` (409).
10. Referential integrity — referenced children must exist, belong to the path parent, and sit in the required state; failures yield `ERR_REFERENTIAL_INTEGRITY` (422).
11. Aggregate open-items gate — approvals and review completions blocked by unresolved work yield `ERR_OPEN_ITEMS_OUTSTANDING` (422).
12. Score thresholds — a score below the tier pass threshold where the endpoint demands a pass yields `ERR_SCORE_BELOW_THRESHOLD` (422).
13. Evidence coverage validity — a coverage period whose end does not follow its start, or a coverage gap beyond the allowed window, yields `ERR_EVIDENCE_COVERAGE_INVALID` (422).
14. Vendor posture gates — an operation the vendor's posture does not permit yields `ERR_VENDOR_POSTURE_BLOCKS` (422).
15. Template gates — issuance against a non-published template yields `ERR_TEMPLATE_NOT_PUBLISHED` (422); retiring a template still referenced by non-terminal cycles yields `ERR_TEMPLATE_IN_USE` (409).
16. Response completeness — a submission missing answers without justification yields `ERR_RESPONSE_INCOMPLETE` (422).
17. Plan task completeness — verification without the full task set yields `ERR_PLAN_TASKS_INCOMPLETE` (422).
18. Evidence pending review — completing evidence review while artifacts remain unreviewed yields `ERR_EVIDENCE_PENDING_REVIEW` (422).
19. Acceptance expiry at decision time — deciding an acceptance whose `expires_at` has passed yields `ERR_ACCEPTANCE_EXPIRED` (422).
20. Alert escalatability — escalation of a low-severity alert or against an ineligible posture yields `ERR_ALERT_NOT_ESCALATABLE` (422).
21. Outstanding addendum — cycle approval blocked by an unsigned, unwaived addendum yields `ERR_ADDENDUM_OUTSTANDING` (422).
22. Offboarding blockers — attestation verification while cycles or alerts remain open yields `ERR_OFFBOARDING_BLOCKED` (422).
23. Pagination bounds — evaluated last; out-of-bounds paging yields `ERR_PAGINATION_INVALID` (422).

### 2.10. Numeric Precision, Scores, and Date Arithmetic

All scores and composite numeric results in the platform are carried to exactly 2 decimal places using round-half-up rounding. Intermediate per-item and per-artifact products are never rounded; only the final stored value is rounded. Tier assignment is pure integer arithmetic and involves no rounding at all. Clause-set derivation is set semantics — a sorted union with no numeric rounding. All deadline arithmetic operates at day granularity on top of the logical clock: windows, cadences, pull-forwards, and deadline extensions are whole-day offsets from a clock instant.

### 2.11. Hierarchical Consistency and Version Cascades

A vendor's `posture` is not set directly by clients; it is a computed aggregate that follows the outcomes of the vendor's child objects — cycle issuance, cycle verdicts, alert escalations, and attestation verification all propagate upward into the vendor record. In the same spirit, a cycle's `open_exception_count` is maintained by the platform as exceptions open and close, and `acceptance_required` follows the cycle's score and acceptance history. Every such cascade is a real mutation: any resource touched by a side effect has its `version` incremented by one and its `updated_at` refreshed, whether the mutation came from a direct client call on that resource or from a parent-child propagation or a clock sweep. Version pinning complements the cascades: a cycle pins the template identity and template version it was issued against, so later template changes never disturb an in-flight cycle.

## 3. Business Logic & Workflows

### 3.1. Vendor Registration, Tier Policy, and the Risk Baseline

A `RiskAnalyst` registers a new vendor by supplying its `legal_name` and three classification attributes: `data_sensitivity` — the highest sensitivity of data shared with the vendor, one of `PUBLIC`, `INTERNAL`, `CONFIDENTIAL`, or `REGULATED`; `access_level` — the breadth of system and facility access granted, one of `NONE`, `READ_ONLY`, `OPERATOR`, or `PRIVILEGED`; and `criticality` — the business impact if the vendor fails, one of `LOW`, `MEDIUM`, `HIGH`, or `MISSION_CRITICAL`. A freshly registered vendor begins in the `ONBOARDING` posture with no cycle in flight, so its `active_cycle_id` is null, and its `offboarding_deadline` is likewise null until offboarding begins. The vendor directory can be filtered by `posture`, by `current_tier`, or by `active_cycle_id`.

Assessment tiers are governed by the single active **AssessmentTierPolicy**, which a `PlatformAdmin` maintains. A policy carries a human-readable `name`, an `active` flag defaulting to true, a `tier_matrix` mapping classification triples to tiers, and four reassessment cadences — `tier1_reassessment_months` defaulting to 36, `tier2_reassessment_months` to 24, `tier3_reassessment_months` to 12, and `tier4_reassessment_months` to 6. Exactly one policy may be active at a time: creating a policy with `active` true deactivates whichever policy was active before, and any attempt that would leave two active policies is rejected with `ERR_UNIQUENESS_VIOLATION` (HTTP 409). The policy list supports an `active` filter so analysts can confirm which policy is in force.

Tier assignment runs at vendor registration, whenever a `RiskAnalyst` revises any of the three classification attributes, and again at cycle issuance, and it always consults the currently active policy. If the vendor's exact triple of `data_sensitivity`, `access_level`, and `criticality` appears as a key in the policy's `tier_matrix`, the matrix's tier wins outright — even when the arithmetic fallback below would produce a different tier. When the triple is absent from the matrix, the platform falls back to a rank sum: sensitivity ranks zero for `PUBLIC`, one for `INTERNAL`, two for `CONFIDENTIAL`, and three for `REGULATED`; access ranks zero for `NONE`, one for `READ_ONLY`, two for `OPERATOR`, and three for `PRIVILEGED`; criticality ranks zero for `LOW`, one for `MEDIUM`, two for `HIGH`, and three for `MISSION_CRITICAL`. The three ranks are summed into a score from zero to nine: a sum of seven or higher yields `TIER_4`, five or six yields `TIER_3`, three or four yields `TIER_2`, and two or lower yields `TIER_1`. `TIER_4` is the strictest tier and `TIER_1` the least strict. The result is stored on the vendor as `current_tier`, and any attribute revision also refreshes the vendor's `risk_score` and increments the vendor's `version` by one.

Every vendor also carries a `risk_score`, a composite on a 0.00 to 100.00 scale built from the vendor's posture, its unresolved monitoring alerts, its accepted residual exceptions, and its imminently expiring risk acceptances; the full formula lives with the monitoring workflow in §3.8. The score is computed at registration and refreshed on every posture change, attribute revision, cycle closure, alert event, and acceptance expiry.

Vendor-side respondents are provisioned as **VendorContact** records: a `RiskAnalyst` adds each contact with an `email` — unique within the vendor — a `full_name`, and an optional `is_primary` flag that defaults to false. Exactly one contact per vendor may be primary; marking a new contact primary demotes the incumbent, and anything that would leave two primaries is rejected with `ERR_UNIQUENESS_VIOLATION`.

### 3.2. Questionnaire Templates: Drafting, Publication, and Revision

Questionnaire content is versioned through the **QuestionnaireTemplate** lifecycle. A `RiskAnalyst` authors a template in `DRAFT` with a `title`, an `applies_to_tiers` list declaring which tiers the template is eligible for (the tiering logic prefers the highest-priority eligible template when one must be selected for a vendor), and an ordered `items` list in which each item carries an `item_key`, a `prompt`, a positive numeric `weight`, and a `control_domain`.

Publication moves a template `DRAFT → PUBLISHED`. Publishing requires the item list to be non-empty with every item's `weight` greater than zero, and it is refused when another `PUBLISHED` template already covers an identical `applies_to_tiers` set — published templates are unique per tier set. Each publication increments the template's `published_version` by one, a monotonic publication counter, and only the latest `PUBLISHED` version is issuable to vendors; the template's `version` increments by one as well. Templates may be browsed with a `status` filter, and the cycles issued against a given template can be listed in reverse — a cycle remembers the template that generated it.

Retirement moves a template `PUBLISHED → RETIRED`, the terminal state, and is blocked with `ERR_TEMPLATE_IN_USE` (HTTP 409) while any assessment cycle still references the template in a non-terminal status — that is, in `DRAFT`, `ISSUED`, `RESPONSE_RECEIVED`, `SCORED`, `EVIDENCE_REVIEW`, `REMEDIATION`, or `RISK_ACCEPTANCE_REVIEW`. A published template that needs changes is instead revised: revising a `PUBLISHED` template creates a brand-new template row in `DRAFT` that copies the item list and carries the parent's `published_version` unchanged, starting a fresh revision cycle, while the original template's `version` increments by one. The new draft is then edited and published on its own, and its own publication advances the counter from the inherited value.

### 3.3. Opening an Assessment Cycle: Creation, Issuance, and the Response Window

Work on a vendor begins when a `RiskAnalyst` creates an **AssessmentCycle** against the vendor, naming the `template_id` to be used and — per §2.7 — the `expected_vendor_version` guard field. A vendor may have at most one non-terminal cycle at a time; attempting to open a second while one is in flight is rejected with `ERR_CYCLE_ALREADY_ACTIVE` (HTTP 409). Cycle creation is also posture-gated: a vendor whose posture does not permit new assessment work — most sharply an `OFFBOARDED` vendor — is rejected with `ERR_VENDOR_POSTURE_BLOCKS` (HTTP 422). A new cycle starts in `DRAFT`, immediately becomes the vendor's `active_cycle_id`, and bumps the vendor's `version` by one. A vendor's cycles can be listed with a `status` filter, and any cycle can be fetched directly by its `id`.

Issuance is the point of no return. A `RiskAnalyst` may issue the cycle only when the vendor's posture is `ONBOARDING`, `APPROVED`, or `CONDITIONAL`, when the cycle is exactly the vendor's current active cycle, when the pinned template is `PUBLISHED` at issue time (otherwise `ERR_TEMPLATE_NOT_PUBLISHED`, HTTP 422), and when no other cycle for the vendor sits in a non-terminal state. Issuing re-runs tier assignment against the vendor's current attributes, snapshots the result into the cycle's `tier_at_issue`, and refreshes the vendor's `risk_score`. It then pins the questionnaire contract: the cycle's `template_id` and `template_version` are set to the template's current `published_version`, and later re-publication of that template never affects the in-flight cycle. The cycle's `issued_at` is set to the current clock, and `response_due_at` is computed as `issued_at` plus the tier's response window — 45 days for `TIER_1`, 30 days for `TIER_2`, 21 days for `TIER_3`, and 14 days for `TIER_4`. The vendor's posture moves to `ASSESSING`, and both the cycle's and the vendor's `version` increment by one.

If the logical clock passes `response_due_at` without any `SUBMITTED` response on the cycle, the expiry sweep moves the cycle `ISSUED → EXPIRED`. The vendor's posture falls to `SUSPENDED`, its `active_cycle_id` clears to null, and its reassessment horizon is recomputed: `next_reassessment_due` moves to the current clock plus the active policy's `tier4_reassessment_months` months, and a `ReassessmentSchedule` event of kind `ALERT_ESCALATION` records the `previous_due` and `new_due` values. The vendor's `version` increments and its `risk_score` refreshes.

### 3.4. Questionnaire Responses, Revision Loops, and Scoring

Once a cycle is `ISSUED`, the vendor's `VendorContact` drafts a **QuestionnaireResponse**, identifying themselves with `submitted_by` and supplying `answers` — a list of entries pairing each `item_key` with an `answer_value` and, where an item does not apply, an optional `na_justification`. Answer values are `YES`, `PARTIAL`, `NO`, or `NA`. Every `item_key` must exist in the cycle's pinned template version; an unknown key is rejected with `ERR_INVALID_REQUEST` (HTTP 422). The response begins in `DRAFT`.

Submission moves the response `DRAFT → SUBMITTED` and simultaneously moves the cycle `ISSUED → RESPONSE_RECEIVED`. Submitting requires every item in the pinned template to be answered or carried by an `na_justification` — a gap is rejected with `ERR_RESPONSE_INCOMPLETE` (HTTP 422) — and it must reach the server on or before `response_due_at`: an overdue submission against a still-`ISSUED` cycle is rejected with `ERR_DEADLINE_PASSED` (HTTP 422), while a cycle the expiry sweep has already moved to `EXPIRED` rejects the submission at the earlier state check with `ERR_INVALID_STATE` (HTTP 409). A successful submission stamps `submitted_at` and increments the cycle's `version`. A provisional score — the raw ratio described below with no revision penalty — is computed at submission time.

Review is a loop. A `RiskAnalyst` may return a `SUBMITTED` response, moving it to `RETURNED` and incrementing its `revision_count` by one while the cycle stays `RESPONSE_RECEIVED` awaiting resubmission; the vendor then resubmits, moving the response `RETURNED → SUBMITTED`. When the analyst is satisfied enough to score, the scoring step computes the final questionnaire score from the pinned template's items — never the template's latest version. Each item earns its `weight` multiplied by the answer's score: 1.0 for `YES`, 0.5 for `PARTIAL`, and 0.0 for `NO`, while items answered `NA` are excluded from both the earned total and the possible total. The raw score is one hundred times the earned total divided by the possible total, rounded half-up to two decimal places, with per-item products left unrounded until the final sum; if every item was answered `NA`, the possible total is zero and the raw score is 0.0. The revision penalty is then the lesser of five percent of the raw score multiplied by `revision_count`, and 20 points; the cycle's `questionnaire_score` is the raw score minus that penalty, rounded half-up to two decimal places, while the response's `raw_score` records the pre-penalty value.

Scoring has two outcomes. When `questionnaire_score` meets or exceeds the tier pass threshold — 60 for `TIER_1`, 70 for `TIER_2`, 80 for `TIER_3`, 90 for `TIER_4` — the response moves `SUBMITTED → ACCEPTED` and the cycle advances `RESPONSE_RECEIVED → SCORED`. When it falls short, the fail branch fires instead: the response moves to `RETURNED` with `revision_count` incremented, and the cycle remains `RESPONSE_RECEIVED` awaiting a revised submission — a below-threshold score here is a workflow outcome, not an error. Either way the cycle's `version` increments by one.

### 3.5. Evidence Artifacts and the Evidence Review

A scored cycle enters its evidence phase when the `VendorContact` uploads the first **EvidenceArtifact** — moving the cycle `SCORED → EVIDENCE_REVIEW` — and the cycle's `version` increments. Each artifact declares a `kind` of `SOC2_TYPE1`, `SOC2_TYPE2`, `ISO27001`, `PENTEST`, or `OTHER`; a coverage window with `period_start` inclusive and `period_end` exclusive; and the `issued_by` auditor or firm. A `period_end` that does not fall after `period_start` is rejected at upload with `ERR_EVIDENCE_COVERAGE_INVALID` (HTTP 422). Artifacts can be listed per cycle with a `status` filter.

Review proceeds artifact by artifact under a `RiskAnalyst`. Starting review moves an artifact `RECEIVED → UNDER_REVIEW` while the cycle is `EVIDENCE_REVIEW`. Completing a review takes one of two exits: `REVIEWED_CLEAN` when no `OPEN` exception finding references the artifact, or `REVIEWED_WITH_EXCEPTIONS` when at least one exception carries this artifact's `evidence_artifact_id`. Either exit computes the artifact's `coverage_gap_days` — the whole days between its `period_end` and the cycle's `issued_at`. An artifact can instead be rejected outright: rejecting is warranted when `coverage_gap_days` exceeds 180 days or when the coverage window is invalid, and it moves the artifact to `REJECTED` while auto-creating an `ExceptionFinding` with `source` `EVIDENCE`, `severity` `HIGH`, a generated `description` capturing the rejection rationale, and status `OPEN`; the artifact's and the cycle's `version` each increment. Completing a review on an artifact whose gap exceeds 180 days likewise fails coverage validity with `ERR_EVIDENCE_COVERAGE_INVALID`.

When every artifact for the cycle has reached `REVIEWED_CLEAN`, `REVIEWED_WITH_EXCEPTIONS`, or `REJECTED` — completing earlier is rejected with `ERR_EVIDENCE_PENDING_REVIEW` (HTTP 422) — the analyst completes the evidence review, and the platform computes the cycle's `evidence_score`. Only artifacts in `REVIEWED_CLEAN` or `REVIEWED_WITH_EXCEPTIONS` contribute; `REJECTED` artifacts are excluded from the average entirely, and if none qualify the evidence score is 0.0. Each contributing artifact starts from a base by kind — 100 for `SOC2_TYPE2`, 95 for `ISO27001`, 80 for `SOC2_TYPE1`, 70 for `PENTEST`, 50 for `OTHER` — and loses a coverage-gap penalty of up to 30 points: for cycles issued at `TIER_1` or `TIER_2`, the penalty is the gap in days capped at 365, divided by 365, multiplied by 30; for the stricter `TIER_3` and `TIER_4` cycles, the gap is capped at 180 and divided by 180 instead, making the penalty climb twice as steeply. The adjusted artifact values are averaged without intermediate rounding, then the platform subtracts severity deductions for the cycle's `EVIDENCE`-source exceptions still in `OPEN` or `IN_REMEDIATION` — 25 per `CRITICAL`, 15 per `HIGH`, 8 per `MEDIUM`, and 3 per `LOW` — and the cycle's `evidence_score` is the result rounded half-up to two decimal places, never allowed below zero.

Completion then branches on the cycle's exception landscape. With `open_exception_count` greater than zero, the cycle moves `EVIDENCE_REVIEW → REMEDIATION`, the composite score is computed, and any required contract addendum is generated (§3.7). With `open_exception_count` at zero but `acceptance_required` true — a composite below threshold whose exceptions were all closed through acceptance — the cycle moves `EVIDENCE_REVIEW → RISK_ACCEPTANCE_REVIEW`. The clean pass moves the cycle `EVIDENCE_REVIEW → APPROVED` outright, but only when every artifact is `REVIEWED_CLEAN`, no exception remains open, the composite meets or exceeds the tier pass threshold (a shortfall on this clean-approval path is rejected with `ERR_SCORE_BELOW_THRESHOLD`, HTTP 422), and no `REQUIRED` or `DRAFTED` addendum is outstanding; approval-blocking residue that fits none of these branches is rejected with `ERR_OPEN_ITEMS_OUTSTANDING` (HTTP 422). A clean approval moves the vendor's posture to `APPROVED`, sets `next_reassessment_due` to the current clock plus the active policy's cadence months for the vendor's `current_tier`, appends a `ReassessmentSchedule` event of kind `TIER_CADENCE`, clears `active_cycle_id`, and increments the vendor's `version`.

### 3.6. Exception Findings: Remediation Plans and Risk Acceptances

An **ExceptionFinding** records a specific gap discovered during the cycle. A `RiskAnalyst` creates one with a `source` of `QUESTIONNAIRE`, `EVIDENCE`, or `MONITORING`; a `severity` of `LOW`, `MEDIUM`, `HIGH`, or `CRITICAL`; a narrative `description`; and — required exactly when the `source` is `EVIDENCE` — the `evidence_artifact_id` of the artifact it was found in, which must belong to the same cycle. A missing artifact reference on evidence-sourced exceptions is an `ERR_INVALID_REQUEST`; a reference that does not exist or does not belong to the path cycle fails with `ERR_REFERENTIAL_INTEGRITY` (HTTP 422). Each new exception opens in `OPEN` status and raises the cycle's `open_exception_count` by one, bumping the cycle's `version`. Exceptions are readable per cycle or through a flat cross-cycle list, both filterable by `status`, `severity`, `evidence_artifact_id`, or `cycle_id`, and a single exception is fetchable by its `id`. An `OPEN` exception that proves unfounded can be closed `OPEN → CLOSED_FALSE_POSITIVE` with a non-empty `closure_reason`, decrementing `open_exception_count` by one.

Exceptions that are real are discharged through a **RemediationPlan**. A `RiskAnalyst` proposes a plan with a non-empty `exception_ids` list — every referenced exception must belong to the cycle and currently be `OPEN`, or the proposal fails with `ERR_REFERENTIAL_INTEGRITY` — and a `tasks` list whose entries carry a `task_key`, a `description`, a `due_at`, and an `owner`. The plan starts `PROPOSED`; a `RiskAnalyst` may reject a `PROPOSED` plan outright, or accept it while the cycle is `REMEDIATION` and every referenced exception is still `OPEN`. Acceptance records the analyst's `X-User-ID` in the plan's `approved_by` and moves every linked exception `OPEN → IN_REMEDIATION` — the exceptions are still open, so `open_exception_count` does not change. Plans can be listed with a `status` filter.

Execution belongs to the vendor. A `VendorContact` reports progress with `completed_task_keys`: a non-empty subset of the plan's task keys moves the plan `ACCEPTED → IN_PROGRESS`, and once the reported set equals the full set of task keys the plan moves to `COMPLETED` — reachable from `IN_PROGRESS`, or directly from `ACCEPTED` when all keys are reported at once. Verification returns to a `RiskAnalyst` and acts only on a `COMPLETED` plan; per §2.8 the verifier must differ from the analyst recorded in `approved_by`. Verification without rejection also demands that `completed_task_keys` equal the full task key set, otherwise `ERR_PLAN_TASKS_INCOMPLETE` (HTTP 422). A passing verification moves the plan `COMPLETED → VERIFIED`, stamps `verified_at`, and cascades: every linked exception moves to `CLOSED_REMEDIATED` with its `closure_reason` taken from the verification note, and the cycle's `open_exception_count` drops by the number of linked exceptions. A failed verification — invoked with `reject` set true — moves the plan to `REJECTED` and compensates by returning every linked exception to `OPEN`, leaving `open_exception_count` unchanged; plan and cycle versions increment accordingly.

The alternative discharge is a **RiskAcceptance**. A `RiskAnalyst` requests one with a non-empty `exception_ids` list — every referenced exception must be `OPEN` or `IN_REMEDIATION` — plus a `justification`, a list of `compensating_controls`, and an `expires_at` that must lie in the future, failing which the request is rejected with `ERR_DEADLINE_PASSED` (HTTP 422). The acceptance starts `REQUESTED`. Approval belongs to a `SecurityApprover` who is not the requester (§2.8), requires every referenced exception still in `OPEN` or `IN_REMEDIATION`, requires `expires_at` still ahead of the clock — a decision on an acceptance whose expiry has passed but whose sweep has not yet fired is rejected with `ERR_ACCEPTANCE_EXPIRED` (HTTP 422) — and carries the `expected_cycle_version` OCC guard of §2.7 against the parent cycle. Approval records `decided_by`, moves every referenced exception to `CLOSED_ACCEPTED`, decrements `open_exception_count` by the number of referenced exceptions, sets the cycle's `acceptance_required` to true, and increments both the acceptance's and the cycle's `version`. Rejection records `decided_by` as well and ends the acceptance in `REJECTED`; the same requester-versus-decider segregation and expiry checks apply. Acceptances can be listed with a `status` filter.

Acceptances are time-boxed. When the clock passes an `APPROVED` acceptance's `expires_at`, the expiry sweep moves it `APPROVED → EXPIRED`: every exception it had closed reopens to `OPEN` with `closure_reason` set to `ACCEPTANCE_EXPIRED`; when the owning cycle is non-terminal, its `open_exception_count` rises by the number of reopened exceptions. The vendor's `next_reassessment_due` is pulled forward to the current clock plus 30 days whenever the existing date is later — it never moves later than its current value — and a `ReassessmentSchedule` event of kind `ACCEPTANCE_EXPIRY` is appended with its `reason_ref` pointing at the expired acceptance. The vendor's `version` increments and its `risk_score` refreshes.

### 3.7. Cycle Verdicts, the Composite Score, and Contract Addenda

Two component scores roll up into the cycle's `composite_score`: forty percent of `questionnaire_score` plus sixty percent of `evidence_score`, rounded half-up to two decimal places, computed only when both components are present. The composite is computed at evidence-review completion and re-computed when remediation resolves. The cycle's `acceptance_required` flag is true whenever the composite falls below the tier pass threshold — 60, 70, 80, or 90 for `TIER_1` through `TIER_4` respectively — or whenever any exception in the cycle has been closed through an approved risk acceptance.

A cycle in `REMEDIATION` resolves when every remediation plan sits in `VERIFIED` or `REJECTED` and `open_exception_count` has fallen to zero; resolving moves the cycle `REMEDIATION → RISK_ACCEPTANCE_REVIEW` and re-runs the composite.

Final judgment belongs to the `SecurityApprover`. Approving a cycle in `RISK_ACCEPTANCE_REVIEW` requires `open_exception_count` at zero, every risk acceptance for the cycle decided into `APPROVED` or `REJECTED`, and no `REQUIRED` or `DRAFTED` contract addendum outstanding — only `SIGNED` or `WAIVED` addenda may remain. Open residue is rejected with `ERR_OPEN_ITEMS_OUTSTANDING`, an outstanding addendum specifically with `ERR_ADDENDUM_OUTSTANDING` (HTTP 422), and per §2.8 the approver must differ from the analyst who completed the evidence review. Approval moves the vendor's posture to `CONDITIONAL` when any `APPROVED` risk acceptance exists for the cycle, otherwise to `APPROVED`. The reassessment cadence is recomputed from the current clock plus the active policy's cadence months for the vendor's `current_tier` — halved when the vendor lands on `CONDITIONAL` — and a `ReassessmentSchedule` event of kind `TIER_CADENCE` is appended; `active_cycle_id` clears, the vendor's `version` increments, and its `risk_score` refreshes. Rejecting the cycle instead moves it to `REJECTED`, drops the vendor's posture to `SUSPENDED`, clears `active_cycle_id`, and increments the vendor's `version`.

Contract addenda are generated, not authored ad hoc. When a cycle completes evidence review on the remediation path, the platform derives a **ContractAddendum** whose `clause_set` is the sorted union of the tier's base clauses and any exception-driven clauses. The base set grows with strictness: `TIER_1` requires `C_DPA`; `TIER_2` adds `C_BREACH_NOTIFY`; `TIER_3` further adds `C_AUDIT_RIGHT`; and `TIER_4` adds `C_ENCRYPTION` and `C_SUBPROCESSOR_FLOWDOWN` on top. Among the cycle's exceptions, any `HIGH`-severity finding — regardless of its status — adds `C_REMEDIATION_TIMELINE`, and any `CRITICAL` adds `C_TERMINATION_RIGHT`. Because every tier contributes at least one clause, the clause set is never empty and a `REQUIRED` addendum is always created on that path, linked to both its vendor and the generating cycle; a vendor's addenda and a cycle's addenda are each listable, with a `status` filter on the vendor view.

The addendum then follows its own small lifecycle. A `RiskAnalyst` moves it `REQUIRED → DRAFTED`; the `VendorContact` executes it by signing with a `signed_at` timestamp that must be present and on or before the current clock, moving it `DRAFTED → SIGNED`; or a `SecurityApprover` waives it from `REQUIRED` with a non-empty `waived_reason`, moving it to `WAIVED`. Each transition increments the addendum's `version` by one.

### 3.8. Continuous Monitoring, Escalation, and the Reassessment Cadence

Between formal cycles, the platform ingests **MonitoringAlert** signals. A `PlatformAdmin` records an alert with a `signal` of `BREACH_REPORT`, `CERT_LAPSE`, `FINANCIAL_DISTRESS`, `NEGATIVE_NEWS`, or `SCAN_FINDING`; a `severity` of `LOW`, `MEDIUM`, `HIGH`, or `CRITICAL`; and a `detected_at` timestamp. The alert opens in `OPEN`, and recording it already refreshes the vendor's `risk_score` and bumps the vendor's `version`. Alerts can be listed with a `status` filter.

A `RiskAnalyst` works the queue: acknowledging moves an `OPEN` alert to `ACKNOWLEDGED` with an optional `disposition` note; dismissing an `ACKNOWLEDGED` alert requires a non-empty `disposition` and moves it to `DISMISSED`, refreshing the vendor's risk score. Escalation is the heavy path and is restricted twice over: the alert must be `ACKNOWLEDGED` with `severity` `HIGH` or `CRITICAL`, and the vendor's posture must be `APPROVED` or `CONDITIONAL` — anything else is rejected with `ERR_ALERT_NOT_ESCALATABLE` (HTTP 422). Escalating moves the alert `ACKNOWLEDGED → ESCALATED`, its terminal state, and pulls the vendor's `next_reassessment_due` forward to the current clock plus 14 days for a `CRITICAL` alert, or plus 30 days for a `HIGH` one, but only ever earlier — if the existing due date is already sooner it stands. The escalation appends a `ReassessmentSchedule` event of kind `ALERT_ESCALATION` whose `reason_ref` points at the alert, moves the vendor's posture to `ASSESSING`, creates a fresh `DRAFT` assessment cycle as the vendor's new `active_cycle_id`, and increments both the alert's and the vendor's `version`. An optional `disposition` may accompany the escalation.

The same pull-forward machinery serves two other events: a risk-acceptance expiry pulls the due date forward to the current clock plus 30 days under the identical never-later rule (§3.6), and whenever `next_reassessment_due` is simply reached for a vendor in `APPROVED` or `CONDITIONAL`, the platform returns the vendor to `ASSESSING` and opens a fresh `DRAFT` cycle as the active cycle. Every movement of the due date is journaled as a **ReassessmentSchedule** event carrying a `kind` of `TIER_CADENCE`, `ALERT_ESCALATION`, `ACCEPTANCE_EXPIRY`, or `OFFBOARDING_SLIP`; the `previous_due` and `new_due` instants; and a polymorphic `reason_ref` holding the driving alert's, acceptance's, or attestation's `id` — or null when none applies. A vendor's schedule history is listable with a `kind` filter.

Monitoring feeds the vendor's standing `risk_score`, whose full rule is: start from a base by posture — 50 for `ONBOARDING`, 60 for `ASSESSING`, 20 for `APPROVED`, 45 for `CONDITIONAL`, 85 for `SUSPENDED`, 70 for `OFFBOARDING`, and 10 for `OFFBOARDED`. Add 5 for every `OPEN` or `ACKNOWLEDGED` alert of `HIGH` severity and 10 for every such `CRITICAL` alert. Add 3 for every exception closed as `CLOSED_ACCEPTED` in the vendor's most recent `APPROVED` cycle — the residual-risk carry-over. Add 8 for every `APPROVED` risk acceptance whose `expires_at` falls sooner than thirty days from the current clock. The total is clamped so it never falls below 0 nor exceeds 100, then rounded half-up to two decimal places. The score refreshes at vendor registration and attribute revision, on every posture change and cycle closure, when alerts are recorded, dismissed, or escalated, and when an acceptance expires.

### 3.9. Subprocessor Disclosures and Vendor Offboarding

Vendors must disclose their own downstream processors. A `VendorContact` files a **SubprocessorDisclosure** with the `subprocessor_name`, the exposed `data_categories`, and the processing `region`; the disclosure begins in `DISCLOSED`, and filing it is posture-gated like other vendor operations, with `ERR_VENDOR_POSTURE_BLOCKS` guarding operations the vendor's posture does not permit. A `RiskAnalyst` opens review, moving the disclosure `DISCLOSED → UNDER_REVIEW`. The decision belongs to a `SecurityApprover` who — per §2.8 — must not be the analyst who started the review: approval requires the vendor's posture to be `APPROVED`, `CONDITIONAL`, or `ASSESSING` and moves the disclosure to `APPROVED`, recording `decided_by`; a vendor in `SUSPENDED`, `OFFBOARDING`, or another non-permitting posture sees the approval rejected with `ERR_VENDOR_POSTURE_BLOCKS`. Rejection moves the disclosure `UNDER_REVIEW → REJECTED` and likewise records `decided_by`. The vendor may retract a disclosure nobody has picked up yet: withdrawing moves it `DISCLOSED → WITHDRAWN`. Disclosures are listable with a `status` filter.

Offboarding begins when a `RiskAnalyst` offboards a vendor — permitted from `ONBOARDING`, `APPROVED`, or `CONDITIONAL` only when no cycle is in flight, and from `SUSPENDED` without that restriction. Offboarding moves the vendor's posture to `OFFBOARDING`, creates an **OffboardingAttestation** in `REQUESTED`, and sets the vendor's `offboarding_deadline` to the current clock plus 90 days, incrementing the vendor's `version`.

The attestation is the vendor's sworn exit statement. The `VendorContact` submits it — while the vendor is `OFFBOARDING` and before `offboarding_deadline`, failing which the submission is rejected with `ERR_DEADLINE_PASSED` — with two boolean assertions, `data_returned` and `data_destroyed`, plus the signatory `attested_by`. At least one of the two assertions must be true; a submission asserting neither is rejected with `ERR_ATTESTATION_INCOMPLETE` (HTTP 422), and whenever `data_destroyed` is true a non-empty `destruction_method` must accompany it, failing which the submission is rejected with `ERR_INVALID_REQUEST`. A valid submission stamps `submitted_at` and moves the attestation `REQUESTED → SUBMITTED`. Attestations are listable with a `status` filter.

A `RiskAnalyst` then verifies or rejects the submission. Verification is blocked while any assessment cycle for the vendor sits in a non-terminal state or any monitoring alert remains `OPEN` or `ACKNOWLEDGED` — rejected with `ERR_OFFBOARDING_BLOCKED` (HTTP 422) — but otherwise moves the attestation `SUBMITTED → VERIFIED` and the vendor's posture to `OFFBOARDED`, clears `active_cycle_id` and `next_reassessment_due` to null, and increments both the attestation's and the vendor's `version`. Rejection moves the attestation `SUBMITTED → REJECTED` and triggers the compensation loop: a fresh `OffboardingAttestation` in `REQUESTED` is created for the vendor, the `offboarding_deadline` extends by 30 days, and a `ReassessmentSchedule` event of kind `OFFBOARDING_SLIP` records the old deadline as `previous_due` and the extended deadline as `new_due` with its `reason_ref` pointing at the rejected attestation; the vendor's `version` increments.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource — or add a new member to a collection, such as a contact, a cycle, a response, an artifact, an exception, a plan, or an acceptance — return `201 Created`. Operations that modify or transition an existing resource return `200 OK`, as do all list and detail reads. The API is mounted under `/vsa`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/vsa/_clock/set_current_utc` | Advance the logical clock; fires due sweeps | PlatformAdmin |
| POST | `/vsa/tier-policies` | Create an AssessmentTierPolicy | PlatformAdmin |
| GET | `/vsa/tier-policies` | List tier policies | PlatformAdmin, RiskAnalyst, SecurityApprover |
| GET | `/vsa/tier-policies/{id}` | Get one tier policy | PlatformAdmin, RiskAnalyst, SecurityApprover |
| POST | `/vsa/questionnaire-templates` | Create a template in `DRAFT` | RiskAnalyst |
| GET | `/vsa/questionnaire-templates` | List templates | RiskAnalyst, SecurityApprover, PlatformAdmin |
| GET | `/vsa/questionnaire-templates/{id}` | Get a template | RiskAnalyst, SecurityApprover, PlatformAdmin |
| POST | `/vsa/questionnaire-templates/{id}/publish` | Publish a `DRAFT` template | RiskAnalyst |
| POST | `/vsa/questionnaire-templates/{id}/retire` | Retire a `PUBLISHED` template | RiskAnalyst |
| POST | `/vsa/questionnaire-templates/{id}/revise` | Create a revised `DRAFT` copy from a `PUBLISHED` template | RiskAnalyst |
| GET | `/vsa/questionnaire-templates/{id}/cycles` | List assessment cycles issued against this template | RiskAnalyst, SecurityApprover, PlatformAdmin |
| POST | `/vsa/vendors` | Register a vendor; runs tier assignment and risk scoring | RiskAnalyst |
| GET | `/vsa/vendors` | List vendors | RiskAnalyst, SecurityApprover, PlatformAdmin, VendorContact |
| GET | `/vsa/vendors/{id}` | Get a vendor | RiskAnalyst, SecurityApprover, PlatformAdmin, VendorContact |
| PATCH | `/vsa/vendors/{id}` | Update vendor attributes; re-runs tier assignment | RiskAnalyst |
| POST | `/vsa/vendors/{id}/offboard` | Move vendor to `OFFBOARDING`; creates the attestation | RiskAnalyst |
| POST | `/vsa/vendors/{id}/contacts` | Add a vendor contact | RiskAnalyst |
| GET | `/vsa/vendors/{id}/contacts` | List vendor contacts | RiskAnalyst, SecurityApprover, VendorContact |
| POST | `/vsa/vendors/{id}/cycles` | Create an AssessmentCycle (`DRAFT`); OCC-guarded | RiskAnalyst |
| GET | `/vsa/vendors/{id}/cycles` | List a vendor's cycles | RiskAnalyst, SecurityApprover, VendorContact |
| GET | `/vsa/cycles/{id}` | Get a cycle by id | RiskAnalyst, SecurityApprover, VendorContact |
| GET | `/vsa/cycles/{id}/responses` | List questionnaire responses for a cycle | RiskAnalyst, SecurityApprover, VendorContact |
| GET | `/vsa/cycles/{id}/evidence` | List evidence artifacts for a cycle | RiskAnalyst, SecurityApprover, VendorContact |
| GET | `/vsa/cycles/{id}/exceptions` | List exception findings for a cycle | RiskAnalyst, SecurityApprover, VendorContact |
| GET | `/vsa/cycles/{id}/remediation-plans` | List remediation plans for a cycle | RiskAnalyst, SecurityApprover, VendorContact |
| GET | `/vsa/cycles/{id}/risk-acceptances` | List risk acceptances for a cycle | RiskAnalyst, SecurityApprover |
| POST | `/vsa/vendors/{vid}/cycles/{id}/issue` | Issue a cycle; pins the template version; vendor to `ASSESSING` | RiskAnalyst |
| POST | `/vsa/vendors/{vid}/cycles/{id}/score` | Score the submitted questionnaire response | RiskAnalyst |
| POST | `/vsa/vendors/{vid}/cycles/{id}/evidence-review/complete` | Complete evidence review; runs evidence and composite scores; may create an addendum | RiskAnalyst |
| POST | `/vsa/vendors/{vid}/cycles/{id}/remediation/resolve` | Resolve the remediation phase; re-runs the composite | RiskAnalyst |
| POST | `/vsa/vendors/{vid}/cycles/{id}/approve` | Approve a cycle in `RISK_ACCEPTANCE_REVIEW` | SecurityApprover |
| POST | `/vsa/vendors/{vid}/cycles/{id}/reject` | Reject a cycle | SecurityApprover |
| POST | `/vsa/vendors/{vid}/cycles/{cid}/responses` | Create a `DRAFT` response for an issued cycle | VendorContact |
| POST | `/vsa/vendors/{vid}/cycles/{cid}/responses/{id}/submit` | Submit or resubmit a response | VendorContact |
| POST | `/vsa/vendors/{vid}/cycles/{cid}/responses/{id}/return` | Return a response for revision | RiskAnalyst |
| POST | `/vsa/vendors/{vid}/cycles/{cid}/evidence` | Upload an evidence artifact | VendorContact |
| POST | `/vsa/vendors/{vid}/cycles/{cid}/evidence/{id}/start-review` | Start review of an artifact | RiskAnalyst |
| POST | `/vsa/vendors/{vid}/cycles/{cid}/evidence/{id}/complete-review` | Complete review, with or without exceptions | RiskAnalyst |
| POST | `/vsa/vendors/{vid}/cycles/{cid}/evidence/{id}/reject` | Reject an artifact; auto-creates a `HIGH` exception | RiskAnalyst |
| GET | `/vsa/exceptions/{id}` | Get a single exception finding by id | RiskAnalyst, SecurityApprover, VendorContact |
| GET | `/vsa/exceptions` | Flat filtered list of exception findings across cycles | RiskAnalyst, SecurityApprover, VendorContact |
| POST | `/vsa/vendors/{vid}/cycles/{cid}/exceptions` | Create an exception finding | RiskAnalyst |
| POST | `/vsa/vendors/{vid}/cycles/{cid}/exceptions/{id}/mark-false-positive` | Close an exception as false positive | RiskAnalyst |
| POST | `/vsa/vendors/{vid}/cycles/{cid}/remediation-plans` | Propose a remediation plan over `OPEN` exceptions | RiskAnalyst |
| POST | `/vsa/vendors/{vid}/cycles/{cid}/remediation-plans/{id}/accept` | Accept a plan; linked exceptions to `IN_REMEDIATION` | RiskAnalyst |
| POST | `/vsa/vendors/{vid}/cycles/{cid}/remediation-plans/{id}/reject` | Reject a `PROPOSED` plan | RiskAnalyst |
| POST | `/vsa/vendors/{vid}/cycles/{cid}/remediation-plans/{id}/progress` | Vendor reports task progress | VendorContact |
| POST | `/vsa/vendors/{vid}/cycles/{cid}/remediation-plans/{id}/verify` | Verify or reject a completed plan; verifier differs from accepter | RiskAnalyst |
| POST | `/vsa/vendors/{vid}/cycles/{cid}/risk-acceptances` | Request a risk acceptance over exceptions | RiskAnalyst |
| POST | `/vsa/vendors/{vid}/cycles/{cid}/risk-acceptances/{id}/approve` | Approve a risk acceptance; OCC-guarded on the cycle; SoD vs requester | SecurityApprover |
| POST | `/vsa/vendors/{vid}/cycles/{cid}/risk-acceptances/{id}/reject` | Reject a risk acceptance | SecurityApprover |
| GET | `/vsa/vendors/{id}/addenda` | List addenda for a vendor | RiskAnalyst, SecurityApprover, VendorContact |
| GET | `/vsa/cycles/{id}/addenda` | List addenda generated by a cycle | RiskAnalyst, SecurityApprover, VendorContact |
| POST | `/vsa/vendors/{id}/addenda/{aid}/draft` | Draft a `REQUIRED` addendum | RiskAnalyst |
| POST | `/vsa/vendors/{id}/addenda/{aid}/sign` | Vendor signs an addendum | VendorContact |
| POST | `/vsa/vendors/{id}/addenda/{aid}/waive` | Waive an addendum | SecurityApprover |
| POST | `/vsa/vendors/{id}/monitoring-alerts` | Record a monitoring alert | PlatformAdmin |
| GET | `/vsa/vendors/{id}/monitoring-alerts` | List alerts for a vendor | RiskAnalyst, SecurityApprover, PlatformAdmin |
| POST | `/vsa/vendors/{id}/monitoring-alerts/{aid}/acknowledge` | Acknowledge an alert | RiskAnalyst |
| POST | `/vsa/vendors/{id}/monitoring-alerts/{aid}/dismiss` | Dismiss an alert | RiskAnalyst |
| POST | `/vsa/vendors/{id}/monitoring-alerts/{aid}/escalate` | Escalate an alert; pulls reassessment forward and opens a new cycle | RiskAnalyst |
| POST | `/vsa/vendors/{id}/subprocessors` | Disclose a subprocessor | VendorContact |
| GET | `/vsa/vendors/{id}/subprocessors` | List subprocessor disclosures | RiskAnalyst, SecurityApprover, VendorContact |
| POST | `/vsa/vendors/{id}/subprocessors/{sid}/start-review` | Start review of a disclosure | RiskAnalyst |
| POST | `/vsa/vendors/{id}/subprocessors/{sid}/approve` | Approve a subprocessor; SoD vs review starter | SecurityApprover |
| POST | `/vsa/vendors/{id}/subprocessors/{sid}/reject` | Reject a subprocessor | SecurityApprover |
| POST | `/vsa/vendors/{id}/subprocessors/{sid}/withdraw` | Withdraw a disclosure | VendorContact |
| GET | `/vsa/vendors/{id}/offboarding-attestations` | List attestations for a vendor | RiskAnalyst, SecurityApprover, VendorContact |
| POST | `/vsa/vendors/{id}/offboarding-attestations/{aid}/submit` | Vendor submits an attestation | VendorContact |
| POST | `/vsa/vendors/{id}/offboarding-attestations/{aid}/verify` | Verify an attestation; vendor to `OFFBOARDED` | RiskAnalyst |
| POST | `/vsa/vendors/{id}/offboarding-attestations/{aid}/reject` | Reject an attestation; creates a fresh `REQUESTED` attestation | RiskAnalyst |
| GET | `/vsa/vendors/{id}/reassessment-schedule` | List reassessment schedule events for a vendor | RiskAnalyst, SecurityApprover, PlatformAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_CYCLE_ALREADY_ACTIVE` | 409 |
| `ERR_UNIQUENESS_VIOLATION` | 409 |
| `ERR_TEMPLATE_IN_USE` | 409 |
| `ERR_STALE_VENDOR_VERSION` | 412 |
| `ERR_STALE_CYCLE_VERSION` | 412 |
| `ERR_INVALID_REQUEST` | 422 |
| `ERR_SEGREGATION_OF_DUTIES` | 422 |
| `ERR_STALE_VERSION` | 422 |
| `ERR_DEADLINE_PASSED` | 422 |
| `ERR_TEMPLATE_NOT_PUBLISHED` | 422 |
| `ERR_RESPONSE_INCOMPLETE` | 422 |
| `ERR_SCORE_BELOW_THRESHOLD` | 422 |
| `ERR_OPEN_ITEMS_OUTSTANDING` | 422 |
| `ERR_REFERENTIAL_INTEGRITY` | 422 |
| `ERR_PLAN_TASKS_INCOMPLETE` | 422 |
| `ERR_EVIDENCE_COVERAGE_INVALID` | 422 |
| `ERR_EVIDENCE_PENDING_REVIEW` | 422 |
| `ERR_ACCEPTANCE_EXPIRED` | 422 |
| `ERR_VENDOR_POSTURE_BLOCKS` | 422 |
| `ERR_ATTESTATION_INCOMPLETE` | 422 |
| `ERR_ALERT_NOT_ESCALATABLE` | 422 |
| `ERR_ADDENDUM_OUTSTANDING` | 422 |
| `ERR_OFFBOARDING_BLOCKED` | 422 |
| `ERR_PAGINATION_INVALID` | 422 |
