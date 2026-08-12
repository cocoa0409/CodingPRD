# Production Insurance API — Product Requirements Document

## 1. Introduction

Entertainment productions carry an unusually dense insurance footprint. A single feature shoot may simultaneously need general liability cover for its locations, an equipment floater for rented gear, cast insurance keyed to medical examinations, errors-and-omissions cover gated on legal clearances, foreign travel extensions for overseas units, and — whenever the budget or a financier demands it — a completion bond guaranteeing delivery. Brokers, production managers, carrier underwriters, claims adjusters, clearance counsel, sureties, and external payroll auditors all touch the same production record, often within the same week, and each party is permitted only a narrow slice of the overall workflow.

This document specifies a broker-hosted Production Insurance API that manages that footprint end to end: registering productions, quoting and binding policies across five coverage lines, clearing cast members and issuing cast endorsements, tracking E&O clearance items, issuing certificates of insurance to location owners, vendors, rental houses, and municipalities, approving foreign travel extensions, underwriting completion bonds, adjusting and settling claims, and reconciling premiums after the shoot through payroll audits and renewal offers. A derived signal called **coverage posture** sits at the center of the design: it continuously summarizes whether a production's coverage, clearances, cast exams, open claims, and bond are in good standing, and it gates precisely the operations — certificate issuance, foreign travel approval, bond issuance — that expose third parties to the production's risk.

The audience is the engineering team building the service. Everything in this document is implementation-facing: role names, state names, field names, error identifiers, and numeric constants are contractual and must be reproduced exactly as written.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every API request carries two headers: `X-User-ID`, identifying the acting operator, and `X-User-Role`, carrying one of eight declared role names. A request that is missing either header, or whose header values are malformed, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is well-formed but not authorized for the target endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403).

The eight roles are `BrokerAgent`, `ProductionManager`, `UnderwriterAgent`, `ClaimsAdjuster`, `ClearanceCounsel`, `SuretyUnderwriter`, `ExternalAuditor`, and `PlatformOperator`. A `BrokerAgent` is the insurance broker's account executive and owns productions, policies, and certificates. A `ProductionManager` sits on the production side: registering cast members, reporting claims, applying for the completion bond, requesting foreign travel, disputing payroll audits, and deciding renewal offers. An `UnderwriterAgent` represents the carrier: recording physical exam outcomes, creating and issuing cast endorsements, ruling on foreign travel extensions, and creating renewal offers. A `ClaimsAdjuster` acknowledges, adjusts, settles, denies, and closes claims. A `ClearanceCounsel` registers and resolves E&O clearance items. A `SuretyUnderwriter` underwrites, issues, claims against, and lapses completion bonds. An `ExternalAuditor` schedules and submits payroll audits. A `PlatformOperator` drives the server's logical clock and otherwise holds read access.

For every one of these eight roles — `BrokerAgent`, `ProductionManager`, `UnderwriterAgent`, `ClaimsAdjuster`, `ClearanceCounsel`, `SuretyUnderwriter`, `ExternalAuditor`, and `PlatformOperator` alike — `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record the acting role (for example as `actor_role` on claim events), and it compares `X-User-ID` values against each other in exactly one place — the segregation-of-duties rule that forbids settling a claim with the same operator identifier that submitted it — but it never compares `X-User-ID` against any entity's `id`.

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

List endpoints accept two query parameters: `limit` and `offset`. The `limit` parameter defaults to 10, with a minimum of 1 and a maximum of 100; the `offset` parameter defaults to 0. Results are always sorted by `created_at` in ascending order. The `meta` object of every list response carries four pagination fields: `limit`, `offset`, `total_count`, and `has_more`. Individual list endpoints additionally accept the resource-specific filter parameters called out in the §3 workflows (for example `status` or `coverage_posture` on the production list).

### 2.4. Resource Identity, Timestamps, and Versioning

Every persisted resource carries an `id` that is a server-minted UUID with no type prefix, a `created_at` timestamp, an `updated_at` timestamp, and an integer `version`. Both timestamps are ISO 8601 UTC with three fractional digits. The `version` starts at 1 when the resource is created and increments by one on every mutation of that resource; `updated_at` refreshes on the same mutations. Claim events are the single exception: as an append-only log they carry only `id` and `created_at`, and neither `updated_at` nor `version` exists on them.

### 2.5. The Logical Clock and Time-Driven Lifecycle Changes

The server maintains a logical clock rather than consulting the wall clock. At boot the logical clock reads exactly 2026-05-01T00:00:00Z, and the server must not fall back to wall-clock time before the first clock-set call arrives. A `PlatformOperator` advances the clock through a dedicated test-driving capability whose request body carries a single field, `to_iso8601`; the response echoes the resulting `current_utc`.

Advancing the clock is never a passive read-only act. Every time-based automatic transition whose threshold has been crossed fires as a side effect of setting the clock: a `BOUND` policy activates once the clock reaches its `effective_date`, an `ACTIVE` policy expires once the clock reaches its `expiry_date` (provided no renewal offer for it is still open), a cleared or conditional cast exam lapses to `EXPIRED` once the clock reaches `physical_exam_expires_at`, an `ENDORSED_PENDING` policy activates once its last draft endorsement resolves and its `effective_date` has been reached, an issued certificate expires once the clock passes `location_end`, an approved travel extension activates at `travel_window_start` and expires once the clock passes `travel_window_end`, and an unanswered renewal offer expires once the clock reaches `offer_expires_at`.

### 2.6. Monetary Amounts, Rounding, and the Minimum Premium

All monetary values are represented as integer numbers of cents in fields whose names end in `_cents`. Whenever a computation produces a fractional cent, the result is rounded half up to a whole cent. Premium computations round half up after each multiplication step, in the order the factors are applied, rather than rounding once at the end. The bond premium uses a stricter discipline still: each pricing tier's contribution is rounded half up to whole cents first, and only then are the tier contributions summed — summing unrounded contributions and rounding once at the end is not acceptable.

Two domain constants qualify every premium. A minimum premium floor of 25000 cents (250 dollars) applies to each policy premium, and it is applied after the premium has been rounded to whole cents. Loss ratios are expressed in basis-points-of-percent: a value of 10000 means 100.00 percent, and the ratio is always a whole number with no fractional part.

### 2.7. Coverage Posture: The Production-Wide Risk Gate

Each production continuously carries a `coverage_posture`, one of `UNBOUND`, `BOUND_PARTIAL`, `BOUND_FULL`, `RESTRICTED`, or `SUSPENDED`, together with a `posture_reasons` list explaining the current value. The posture is never set directly; it is recomputed after every mutation on the production itself or on any of its policies, cast endorsements, clearance items, claims, completion bond, or cast members. The full derivation, including the fixed evaluation order and the reason codes, is specified in §3.4.

Posture is a gate, not a report. Certificate issuance, foreign travel approval, and completion bond issuance are only permitted when the posture is `BOUND_PARTIAL` or `BOUND_FULL`; a `RESTRICTED` or `SUSPENDED` production is refused with `ERR_POSTURE_BLOCKS_ISSUANCE` (HTTP 422), or with the operation-specific variants `ERR_POSTURE_BLOCKS_FOREIGN` and `ERR_POSTURE_BLOCKS_BOND` described in §3.6 and §3.7.

### 2.8. Optimistic Concurrency Control on Coverage-Sensitive Writes

Three write operations are guarded by optimistic concurrency control, because each computes against a snapshot of a parent resource that another writer may have advanced since the client last read it:

- Issuing a certificate requires the request to carry `expected_production_version`, holding the production `version` the client last observed. If the production's current `version` no longer matches — for example because another writer has just bound a policy, revoked an endorsement, or flagged a clearance item, any of which may have moved `coverage_posture` — the issuance is rejected with `ERR_STALE_VERSION` (HTTP 412).
- Binding a policy likewise requires `expected_production_version` matching the production's current `version`. A mismatch means the premium and posture would be computed against a snapshot the production has already moved past, and the bind is rejected with `ERR_STALE_VERSION` (HTTP 412).
- Accepting a renewal offer requires `expected_policy_version` matching the policy's current `version`. If the policy's version has advanced since the client last read it — say a payroll audit has posted in the meantime — the acceptance is rejected with `ERR_STALE_VERSION` (HTTP 412).

The version field on each of these three requests is non-optional. No other endpoint accepts a version field at all.

### 2.9. Request Validation Pipeline and Error Precedence

Inbound requests are validated in a fixed order, and the first failure wins — a response never reports more than one error, and an earlier failure masks everything after it. The sequence is:

1. The `X-User-Role` header must be present and name one of the eight declared roles, and the `X-User-ID` header must be present and well-formed; violations are `ERR_UNAUTHENTICATED` (401).
2. The role must be authorized for the endpoint, per the role assignments in §4; violations are `ERR_FORBIDDEN` (403).
3. Path identifiers are resolved left to right — the production id (`prodId` or, on top-level routes, `id`) before the policy id (`pid`), before the child id (`childId`), and the claim id (`claimId`) before any event beneath it. Any identifier that does not resolve to an existing entity is `ERR_NOT_FOUND` (404).
4. On mutation endpoints, every foreign key in the request body (such as `policy_id` or `cast_member_id`) must resolve to an existing entity; otherwise `ERR_NOT_FOUND` (404).
5. On action endpoints, the target entity must currently sit in a valid source state for the requested transition; otherwise `ERR_INVALID_STATE` (409).
6. On the three OCC-guarded writes named in §2.8, the expected version must match the parent's current `version`; otherwise `ERR_STALE_VERSION` (412).
7. Segregation of duties on claim settlement: the request is refused with `ERR_SELF_SETTLEMENT_FORBIDDEN` (403) when the adjuster's `X-User-ID` equals the identifier that originally submitted the claim.
8. Posture gating on certificate issuance, foreign travel approval, and bond issuance, per §2.7.
9. Cast endorsement gating at issuance — the endorsement type must match the cast member's exam status, essential-element flag, and role tier — with violations rejected as `ERR_CAST_ENDORSEMENT_INVALID` (422).
10. Referenced-target state compatibility: a claim's policy must be in a claimable state at reporting time, and a completion bond may only be underwritten for a production that requires one; violations are `ERR_REFERENCED_STATE_INVALID` (422).
11. Conditional field presence — most notably `additional_insured_name` on `LOCATION` and `PERMIT` certificates — with violations rejected as `ERR_ADDITIONAL_INSURED_REQUIRED` (400).
12. Enum membership for every enum-typed field (`coverage_line`, `claim_type`, `endorsement_type`, and the rest); an undeclared value is `ERR_INVALID_ENUM` (400).
13. Datetime ordering: every end must fall strictly after its start, and a claim's `occurrence_date` must lie inside the referenced policy's effective window; violations are `ERR_TEMPORAL_RANGE_INVALID` (422).
14. Certificate window containment against the production envelope and all bound policy windows, rejected as `ERR_CERT_WINDOW_OUTSIDE_POLICY` (422) and detailed in §3.5.
15. Foreign travel no-overlap and buffer-window rules, rejected as `ERR_FOREIGN_TRAVEL_OVERLAP` (422) and detailed in §3.6.
16. Logical-clock windows: a renewal offer must not have expired and a certificate's coverage window must not already have elapsed; violations are `ERR_WINDOW_ELAPSED` (422).
17. Fiscal sanity: a claim's `loss_amount_cents` must be positive, a bond amount must cover the mandated share of budget, and a settlement must not exceed the reserve; violations are `ERR_FISCAL_CONSTRAINT_VIOLATED` (422).
18. The aggregate deductible cap check at claim reporting time, rejected as `ERR_DEDUCTIBLE_CAP_EXCEEDED` (422) when the proposed claim would push paid deductibles past the cap.
19. Conditional uniqueness of `certificate_number` and of `policy_number` within a (`carrier_code`, `coverage_line`) pair, rejected as `ERR_DUPLICATE_IDENTIFIER` (409).

Requests whose bodies are missing required fields or carry malformed types, outside the specific checks above, are rejected with `ERR_INVALID_REQUEST` (400). Because earlier checks mask later ones, a caller can rely on this order when diagnosing a rejection: an authentication failure hides everything downstream, and a stale-version rejection surfaces before any posture, temporal, or fiscal check is consulted.

### 2.10. Identifier Uniqueness and Server-Minted Numbers

Two identifiers carry uniqueness obligations beyond the primary key. A policy's `policy_number` must be unique within its (`carrier_code`, `coverage_line`) pair — the same carrier may reuse a number across different coverage lines, but never twice on the same line. A certificate's `certificate_number` is not client-supplied at all: it is minted by the server at issuance time in the format `CERT-<prod>-<seq>`, where the sequence makes each certificate of a production distinct. A collision on either rule is `ERR_DUPLICATE_IDENTIFIER` (HTTP 409), surfaced at policy or certificate creation.

## 3. Business Logic & Workflows

### 3.1. Registering Productions and Placing Coverage

A `BrokerAgent` opens a new engagement by registering the production itself. The registration payload carries the broker-assigned `production_code` (for example PRD-2026-014), the working `title`, the `production_type` — one of `FEATURE`, `EPISODIC`, `DOCUMENTARY`, `COMMERCIAL`, or `MUSIC_VIDEO` — the scheduled shooting window as `principal_photography_start` and `principal_photography_end` (the last shooting day must fall strictly after the first), the total `budget_cents` (strictly greater than zero), and optionally `requires_completion_bond`, which defaults to false and records that the budget or a financier mandates a completion bond. A newly registered production is born in `DRAFT` status, and its `coverage_posture` initializes to `UNBOUND`. The production list view can be filtered by `status` or by `coverage_posture`.

With the production registered, the broker quotes coverage one line at a time. Creating a policy takes the `coverage_line` — `GENERAL_LIABILITY`, `EQUIPMENT`, `CAST`, `ERRORS_OMISSIONS`, or `FOREIGN_TRAVEL` — together with the issuing `carrier_code` (CHUBB, AIG, TRAVELERS, and the like), the carrier-assigned `policy_number`, the per-occurrence `limit_cents` (strictly positive), the `aggregate_limit_cents` (at least the per-occurrence limit), the per-claim `deductible_cents` (zero or more), the policy window as `effective_date` and `expiry_date` (expiry strictly after effective), and the declared `payroll_basis_cents` (zero or more). Every policy is created in `QUOTED` status and points back to its owning production through `production_id`; the policy list view filters by `coverage_line` and `status`.

Binding turns a quote into cover: the policy moves `QUOTED` → `BOUND`, performed by a `BrokerAgent`, and the request must carry `expected_production_version` per §2.8. Binding is only meaningful while the production is in `DRAFT` or `ACTIVE`. Three coverage lines add prerequisites of their own. Binding a `CAST` policy requires every cast member whose `endorsement_required` is true to already hold a `physical_exam_status` of `CLEARED` or `CONDITIONAL`; otherwise the bind is refused with `ERR_CAST_EXAM_INCOMPLETE`. Binding an `ERRORS_OMISSIONS` policy requires every `SCRIPT` and `TITLE` clearance item on the production to be `CLEARED` or `WAIVED`; otherwise the refusal is `ERR_EO_CLEARANCE_INCOMPLETE`. Binding a `FOREIGN_TRAVEL` policy requires a `GENERAL_LIABILITY` policy on the same production to already be `BOUND`, `ENDORSED_PENDING`, or `ACTIVE`; otherwise the refusal is `ERR_GL_PREREQUISITE_MISSING`.

The act of binding also prices the policy. The **provisional premium** starts from the declared `payroll_basis_cents` and multiplies it by a base rate that depends on the coverage line: 1.20 percent for `GENERAL_LIABILITY`, 1.85 percent for `EQUIPMENT`, 2.75 percent for `CAST`, 3.50 percent for `ERRORS_OMISSIONS`, and 4.20 percent for `FOREIGN_TRAVEL`. The product is then scaled by a risk multiplier keyed to the production's `production_type`: 1.00 for `FEATURE`, 1.15 for `EPISODIC`, 0.85 for `DOCUMENTARY`, 0.90 for `COMMERCIAL`, and 1.05 for `MUSIC_VIDEO`. Cast coverage adds two further loadings: a stunt loading of one plus ten hundredths for every cast member whose `role_tier` is `STUNT`, capped at 1.50, and an essential-element loading of 1.20 whenever any cast member on the production carries `essential_element` set to true (1.00 when none does). Foreign travel coverage instead applies a loading of one plus five hundredths per declared traveler (the `travelers_count`), capped at 1.40. Each multiplication step is rounded half up to whole cents before the next factor is applied, and once the rounded figure is known, the 25000-cent minimum premium floor is applied — a policy whose computed premium rounds below the floor is charged the floor instead. The result is stored on the policy as `provisional_premium_cents`.

Binding has two further consequences beyond the policy row itself: the owning production's `version` increments, and the production's `coverage_posture` is recomputed. Thereafter the policy activates on its own — `BOUND` → `ACTIVE` — as soon as the logical clock reaches its `effective_date`, recomputing posture again at that moment. A `BOUND` cast policy can also be held in an intermediate `ENDORSED_PENDING` state when endorsement paperwork is in flight; §3.2 covers that path.

### 3.2. Cast Members, Physical Exams, and Cast Endorsements

Cast insurance begins with the roster. A `ProductionManager` adds each cast member with their `full_name`, a `role_tier` of `PRINCIPAL`, `SUPPORTING`, `DAY_PLAYER`, or `STUNT`, a strictly positive `weekly_salary_cents`, and an optional `essential_element` flag (default false) marking someone the production cannot complete without. From these inputs the system derives `endorsement_required`: it is true whenever the cast member is an essential element or holds the `PRINCIPAL` tier, and false otherwise. Every cast member starts with `physical_exam_status` set to `PENDING`, and the cast list view filters by `role_tier` and `physical_exam_status`.

An `UnderwriterAgent` records the outcome of the medical examination by submitting an `outcome`. A `CLEARED` outcome stamps `physical_exam_expires_at` ninety days into the future from the current logical time; a `CONDITIONAL` outcome stamps it only thirty days out; both of these recordings require that the production is not `CANCELLED`. A `FAILED` outcome carries no precondition, and because a failed exam degrades the production's risk position, it triggers an immediate recomputation of `coverage_posture`. A `CONDITIONAL` exam may later be upgraded to `CLEARED`, which restarts the full ninety-day validity window. When the logical clock reaches `physical_exam_expires_at`, the exam status flips automatically to `EXPIRED`, any `ISSUED` endorsement of type `PHYSICAL_CLEARANCE` referencing that cast member is revoked as part of the same tick, and posture is recomputed. A failed exam is not the end of the road: an underwriter may order a retake, moving the cast member `FAILED` → `PENDING` and clearing `physical_exam_expires_at` back to null.

Endorsements are the carrier's written acceptance of cast risk. An `UnderwriterAgent` drafts one by naming the `cast_member_id`, the `policy_id` (which must belong to a `CAST` policy on the same production), the `endorsement_type` — `PHYSICAL_CLEARANCE`, `ESSENTIAL_ELEMENT`, or `STUNT_RIDER` — and optional free-text `underwriter_notes`. The endorsement is created in `DRAFT`. Drafting an endorsement against a `BOUND` cast policy moves that policy `BOUND` → `ENDORSED_PENDING`: cover is agreed in principle but held until the endorsement paperwork completes.

Issuing an endorsement (`DRAFT` → `ISSUED`) gates on the match between type and cast member. A `PHYSICAL_CLEARANCE` endorsement requires the cast member's exam status to be `CLEARED` or `CONDITIONAL`; an `ESSENTIAL_ELEMENT` endorsement requires `essential_element` to be true; a `STUNT_RIDER` endorsement requires `role_tier` to be `STUNT`. Any mismatch is rejected with `ERR_CAST_ENDORSEMENT_INVALID` (HTTP 422), and the policy holding the endorsement must itself be `BOUND`, `ENDORSED_PENDING`, or `ACTIVE`. Issuance stamps `issued_at`, and it may release a held policy: once no `DRAFT` endorsement remains on an `ENDORSED_PENDING` policy and the logical clock has reached the policy's `effective_date`, the policy moves `ENDORSED_PENDING` → `ACTIVE` automatically. Every issuance and every revocation of an issued endorsement recomputes the production's posture. Revocation works from either `DRAFT` or `ISSUED`, lands the endorsement in the terminal `REVOKED` state, and stamps `revoked_at` (which stays null while the endorsement is active). Endorsement list views — both per production and across productions — filter by `cast_member_id`, `policy_id`, `endorsement_type`, and `status`.

### 3.3. Clearance Items

Errors-and-omissions cover lives and dies by legal clearances. A `ClearanceCounsel` registers each item under review with a `clearance_kind` — `SCRIPT`, `TITLE`, `MUSIC`, `PERSONAL_RIGHTS`, `TRADEMARK`, or `LOCATION_RIGHTS` — a human-readable `item_reference` (for example, "Title report for 'Night Shift'"), the responsible `legal_reviewer`, and optional `notes` for exceptions. Items are born `PENDING`.

Resolution happens through a single decision call carrying an `outcome`. From `PENDING`, counsel may declare the item `CLEARED` or `FLAGGED`; a `FLAGGED` item can subsequently be `CLEARED`, or it can be `WAIVED` — but a waiver additionally requires a non-empty `waiver_justification` explaining why the production proceeds despite the flag. `CLEARED` and `WAIVED` are terminal. Because clearances feed the posture derivation, every resolution recomputes `coverage_posture`, and the clearance list view filters by `clearance_kind` and `status`.

### 3.4. Coverage Posture Derivation and Production Activation

Posture derivation runs after every mutation on the entities listed in §2.7, and its evaluation order is fixed. First, collect the **bound lines**: the set of `coverage_line` values on the production's policies whose status is `BOUND`, `ENDORSED_PENDING`, or `ACTIVE`. Second, compute the **required lines**: always `GENERAL_LIABILITY` and `EQUIPMENT`, plus `CAST` when the production's `production_type` is `FEATURE` or `EPISODIC`. A completion bond requirement is orthogonal to coverage lines — it never adds a required line. Third, the missing lines are those required but not bound. Fourth, count the production's open injury claims: claims whose `claim_type` is `INJURY` and whose status is `SUBMITTED`, `UNDER_REVIEW`, or `ADJUSTED`. Fifth, count uncleared mandatory clearances: clearance items whose `clearance_kind` is `SCRIPT`, `TITLE`, or `PERSONAL_RIGHTS` and whose status is `PENDING` or `FLAGGED`. Sixth, count failed cast exams: cast members with `endorsement_required` true whose `physical_exam_status` is `PENDING`, `FAILED`, or `EXPIRED`. Seventh, when the production requires a completion bond, note the bond's current status.

The posture itself falls out of a strict ladder, evaluated top to bottom. A `CANCELLED` production is always `SUSPENDED`. Otherwise, any open injury claim makes the production `RESTRICTED`; so does any uncleared mandatory clearance; so does a required completion bond that is not yet `ISSUED`. If none of those restrictions apply, a production with no missing lines and no failed cast exams is `BOUND_FULL`; with no missing lines but at least one failed exam it is `BOUND_PARTIAL`; with nothing bound at all it is `UNBOUND`; and anything else — some but not all required lines bound — is `BOUND_PARTIAL`.

The `posture_reasons` list names every contributing cause, sorted lexicographically for determinism: one `MISSING_LINE_<COVERAGE_LINE>` code per missing required line, `OPEN_INJURY_CLAIM` when open injury claims exist, one `MANDATORY_CLEARANCE_OPEN_<KIND>` per uncleared mandatory clearance kind, one `CAST_EXAM_FAILED_<cast_member_id>` per endorsement-required cast member whose exam is not in good standing, and `BOND_NOT_ISSUED` when a required bond has not reached `ISSUED`.

Activation is the production's first gated move: a `BrokerAgent` transitions the production `DRAFT` → `ACTIVE`, and four checks stand in the way. At least one policy must be `BOUND`, `ENDORSED_PENDING`, or `ACTIVE`, or the activation fails with `ERR_NO_BOUND_POLICY`. When `requires_completion_bond` is true, the bond must already be `ISSUED`, or the failure is `ERR_BOND_NOT_ISSUED`. Every cast member with `endorsement_required` true must hold at least one `ISSUED` endorsement, or activation stops with `ERR_CAST_ENDORSEMENT_MISSING`. And every mandatory clearance — `SCRIPT`, `TITLE`, and `PERSONAL_RIGHTS` — must be `CLEARED` or `WAIVED`, or the refusal is `ERR_MANDATORY_CLEARANCE_OPEN`. A successful activation recomputes posture with the production now live.

### 3.5. Certificates of Insurance

Certificates are the production's proof of cover to the outside world — the location owner who wants to be named before a camera rolls, the municipality issuing a permit, the rental house releasing a camera package. A `BrokerAgent` drafts a certificate with the `certificate_type` (`LOCATION`, `VENDOR`, `EQUIPMENT_RENTAL`, or `PERMIT`), the holder's `holder_name` and `holder_address`, the `coverage_lines` the certificate evidences (a subset of `GENERAL_LIABILITY`, `EQUIPMENT`, and `ERRORS_OMISSIONS`), and the coverage-effective window as `location_start` and `location_end`, with the end strictly after the start. The `additional_insured_name` field names the party to be added as additional insured; it is mandatory whenever the certificate is of type `LOCATION` or `PERMIT`, and a missing or empty value is rejected with `ERR_ADDITIONAL_INSURED_REQUIRED` (HTTP 400) both when the certificate is drafted and when it is issued. Drafts sit in `DRAFT` until issued, and the certificate list filters by `certificate_type` and `status`.

Issuance — `DRAFT` → `ISSUED`, by a `BrokerAgent` — is the most heavily gated write in the system. The request must carry `expected_production_version`, and a stale view of the production is refused with `ERR_STALE_VERSION` per §2.8. The production must be `ACTIVE`; issuing against a production in any other state is rejected with `ERR_PRODUCTION_NOT_ACTIVE`. The production's `coverage_posture` must be `BOUND_FULL` or `BOUND_PARTIAL`; a `RESTRICTED` or `SUSPENDED` posture blocks issuance with `ERR_POSTURE_BLOCKS_ISSUANCE`. Every coverage line listed on the certificate must be backed by at least one policy on this production in `BOUND`, `ENDORSED_PENDING`, or `ACTIVE`, or the refusal is `ERR_COVERAGE_LINE_NOT_BOUND`. And the logical clock must not already have passed `location_end` — an elapsed window is rejected with `ERR_WINDOW_ELAPSED` (the issuance transition also refers to this rejection as `ERR_CERT_WINDOW_ELAPSED`).

The coverage window itself is validated against two envelopes, and a violation of either is `ERR_CERT_WINDOW_OUTSIDE_POLICY` (HTTP 422). All intervals here are half-open: the start is inclusive, the end exclusive. First, the certificate window must lie within the production's outer envelope, which runs from `principal_photography_start` to thirty days past `principal_photography_end` — a `location_end` landing exactly on that thirtieth day is allowed, touching the outer boundary. Second, for each coverage line on the certificate, the certificate window must lie within the intersection of every bound policy's `effective_date`-to-`expiry_date` window on that line. A `location_start` exactly equal to a policy's `effective_date` is allowed; a `location_end` exactly equal to a policy's `expiry_date` is not, because it would touch the policy window's exclusive upper boundary.

A successful issuance mints the `certificate_number` (§2.10) and increments the production's `version`. Voiding is a `BrokerAgent` action with an asymmetry worth remembering: a `DRAFT` certificate can always be voided, but an `ISSUED` certificate can be voided only while the logical clock is still before `location_start` — once the coverage window has opened, the certificate must run its course and will later flip `ISSUED` → `EXPIRED` automatically when the clock passes `location_end`, or earlier if the parent production or a policy backing one of its lines expires or is cancelled.

### 3.6. Foreign Travel Extensions

Shoots that leave the home territory need a travel extension per country. A `ProductionManager` files the request with the `territory_code` (an ISO 3166-1 alpha-2 code such as FR or JP), the travel window as `travel_window_start` and `travel_window_end` (end strictly after start), the strictly positive `travelers_count` of cast and crew traveling, and a strictly positive `repatriation_limit_cents` sub-limit for medical repatriation. Requests are born `REQUESTED`, and the extension list filters by `territory_code` and `status`.

Approval rests with an `UnderwriterAgent`, moving the extension `REQUESTED` → `APPROVED`, and three gates apply. The production's posture must be `BOUND_PARTIAL` or `BOUND_FULL`, or approval is refused with `ERR_POSTURE_BLOCKS_FOREIGN`. A `FOREIGN_TRAVEL` policy on the production must be `BOUND`, `ENDORSED_PENDING`, or `ACTIVE`, and the travel window must overlap that policy's effective window. Finally, the new window must not collide with another extension: for the same production and the same `territory_code`, no `APPROVED` or `ACTIVE` extension may overlap the requested window, where intervals are half-open — an extension starting exactly when another ends does not overlap — and the window must also sit entirely within the production's travel envelope, which runs from fourteen days before `principal_photography_start` to fourteen days after `principal_photography_end`, allowing pre-production scouting and post-production wrap travel on each side. Either violation is rejected with `ERR_FOREIGN_TRAVEL_OVERLAP` (HTTP 422).

Denial is also an underwriter action, with its own asymmetry: a `REQUESTED` extension may be denied at any time, but an `APPROVED` extension may be denied only while the logical clock is still before `travel_window_start`. Once the clock reaches `travel_window_start`, an approved extension activates on its own — `APPROVED` → `ACTIVE` — and once the clock passes `travel_window_end` it expires, `ACTIVE` → `EXPIRED`.

### 3.7. Completion Bonds

A production carries at most one completion bond — the bond relationship is one-to-one, and reading it returns an array containing zero or one element. A `ProductionManager` applies by naming the `surety_company` and the `bond_amount_cents`, the penalty amount the surety stands behind; the application is born `APPLIED`.

Underwriting moves the bond `APPLIED` → `UNDERWRITTEN` and belongs to a `SuretyUnderwriter`. The production must actually require a bond — applying the underwrite action to a production whose `requires_completion_bond` is false is rejected with `ERR_REFERENCED_STATE_INVALID` — the production's `budget_cents` must be positive, and the bond amount must cover at least half of the budget, rounded up to whole cents; a shortfall is `ERR_FISCAL_CONSTRAINT_VIOLATED` (HTTP 422). Underwriting prices the bond and locks its terms. The **bond premium** is tiered on `bond_amount_cents`: 2.00 percent on the first 1,000,000 dollars, 1.50 percent on the portion above 1,000,000 dollars up to 5,000,000 dollars, 1.10 percent on the portion above 5,000,000 dollars up to 25,000,000 dollars, and 0.85 percent on any portion above 25,000,000 dollars. Each tier's contribution is rounded half up to whole cents before the contributions are summed, per §2.6, and a bond amount of exactly 1,000,000 dollars falls entirely within the first tier — tier boundaries are inclusive at the lower bound of the next tier. The computed figure is stored as `bond_premium_cents`, and `strike_price_cents` — the takeover threshold the surety will fund up to — is set equal to `bond_amount_cents`.

Issuing the bond (`UNDERWRITTEN` → `ISSUED`) requires the production's posture to be `BOUND_PARTIAL` or `BOUND_FULL`; any other posture is refused with `ERR_POSTURE_BLOCKS_BOND` (HTTP 422). For this gate alone, the §3.4 ladder is evaluated with the bond's own not-yet-issued contribution discounted — a required bond cannot self-block its own issuance, or `ISSUED` would be unreachable and the activation-time `ERR_BOND_NOT_ISSUED` check of §3.4 unsatisfiable. Every other restriction still gates normally: an open injury claim, an uncleared mandatory clearance, missing required lines (a fully `UNBOUND` production), or a `CANCELLED` production still blocks issuance with `ERR_POSTURE_BLOCKS_BOND`. The production's stored `coverage_posture` is unaffected by this discount — it continues to reflect the literal §3.4 derivation, so certificate issuance and foreign travel approval against a production whose required bond is not yet `ISSUED` are still refused. Once issued, two endings matter. A surety may claim against the bond — `ISSUED` → `CLAIMED` — but only while the production has at least one open claim (status `SUBMITTED`, `UNDER_REVIEW`, or `ADJUSTED`) whose `loss_amount_cents` reaches the bond's `strike_price_cents`; claiming the bond cancels every policy on the production, voids every certificate, and recomputes posture. The happier ending is automatic: when the production wraps, an `ISSUED` bond moves to `RELEASED` on its own. Short of either ending, a `SuretyUnderwriter` may lapse the bond — from `APPLIED` only while no claim has been made against it, and from `UNDERWRITTEN` unconditionally — landing it in `LAPSED`.

### 3.8. Claims Handling and the Claim Event Log

Losses are reported by a `ProductionManager`, who names the `policy_id` the loss falls under, the `claim_type` — `DAMAGE`, `INJURY`, `WEATHER_DELAY`, `THEFT`, or `THIRD_PARTY` — the `occurrence_date` of the loss, and the claimed `loss_amount_cents`. The occurrence date must lie within the referenced policy's effective window, or the report is rejected with `ERR_TEMPORAL_RANGE_INVALID`; the loss amount must be strictly positive, or the rejection is `ERR_FISCAL_CONSTRAINT_VIOLATED`. The referenced policy must also be in a compatible state for claims — a report filed against a policy in an incompatible state fails with `ERR_REFERENCED_STATE_INVALID` — and the aggregate deductible cap described below is enforced at reporting time with `ERR_DEDUCTIBLE_CAP_EXCEEDED`. The server stamps `reported_date` at submission, the claim is born `SUBMITTED`, and whenever the new claim is an `INJURY` claim the production's posture is recomputed, because open injuries restrict it.

Deductibles are computed at the moment the claim is created. The **deductible applied** is the smallest of three figures: the policy's per-claim `deductible_cents`, the claim's own `loss_amount_cents`, and the room remaining under the policy's annual aggregate deductible cap. That cap is one quarter of the policy's `aggregate_limit_cents`, and the room remaining is the cap minus the cumulative deductibles already absorbed — the sum of `deductible_applied_cents` over the same policy's claims in `UNDER_REVIEW`, `ADJUSTED`, or `SETTLED` whose `occurrence_date` falls inside the policy's effective window — floored at zero so the room never goes negative. The result is stored as `deductible_applied_cents`, and the carrier's share, `carrier_payable_cents`, is the loss amount minus the deductible applied. The boundary case is exact: when the loss amount equals the per-claim deductible, the deductible applied equals the whole loss and the carrier pays nothing — the claim sits entirely on the production.

From `SUBMITTED`, a `ClaimsAdjuster` acknowledges the claim, moving it to `UNDER_REVIEW`. Acknowledgement refuses claims against policies in `QUOTED` or `CANCELLED` — only `BOUND`, `ENDORSED_PENDING`, `ACTIVE`, or `EXPIRED` policies are claimable, and anything else is rejected with `ERR_POLICY_NOT_CLAIMABLE` — and it initializes `reserve_cents` to the computed `carrier_payable_cents`. Reserve management is then a deliberate loop: adjusting the reserve with a `new_reserve_cents` value of zero or more moves the claim `UNDER_REVIEW` → `ADJUSTED`, and a further adjustment moves it `ADJUSTED` → `UNDER_REVIEW` again; the cycle may repeat as often as the adjuster needs, each pass overwriting `reserve_cents`.

Three terminal paths branch off the review loop. Denial from `UNDER_REVIEW` requires a non-empty `reason`; denial from `ADJUSTED` carries no precondition at all — either way the reserve is zeroed. Settlement takes a `settlement_amount_cents` that must be zero or more and must not exceed the claim's current `reserve_cents` — an overage is rejected with `ERR_SETTLEMENT_EXCEEDS_RESERVE` — and it enforces segregation of duties: the same `X-User-ID` that submitted the claim may not settle it, and a matching pair is refused with `ERR_SELF_SETTLEMENT_FORBIDDEN` (HTTP 403). Settlement zeroes the reserve and lands the claim in `SETTLED`, from either `UNDER_REVIEW` or `ADJUSTED`. Finally, closing moves a `SETTLED` or `DENIED` claim to `CLOSED`.

Every one of these movements appends to an append-only log. Each claim event row records its owning `claim_id`, an `event_type` drawn from `SUBMIT`, `ADJUST_RESERVE`, `DENY`, `SETTLE`, `REOPEN`, and `CLOSE`, a `payload` object carrying event-specific data (for instance the `new_reserve_cents` value on an `ADJUST_RESERVE` event), a server-stamped `recorded_at`, and the `actor_role` that emitted the event. Acknowledgement emits `SUBMIT`; each reserve adjustment emits `ADJUST_RESERVE`; denial emits `DENY`; settlement emits `SETTLE`; closing emits `CLOSE`. The event log is readable per claim, and a flat cross-production view of events filters by `claim_id`, just as the claim lists filter by `policy_id`, `claim_type`, and `status`.

### 3.9. Wrapping and Cancelling a Production

Wrapping is the production's happy ending, performed by a `ProductionManager` as an `ACTIVE` → `WRAPPED` transition. Two gates guard it. Every claim on the production must already be `SETTLED`, `DENIED`, or `CLOSED`, or the wrap is refused with `ERR_OPEN_CLAIMS_BLOCK_WRAP`. And no certificate may still sit in `DRAFT` — draft certificates must be issued or voided first — or the refusal is `ERR_DRAFT_CERTIFICATES_OPEN`. A successful wrap ripples outward: every `ISSUED` certificate auto-expires, every `ACTIVE` foreign travel extension auto-expires, an `ISSUED` completion bond auto-transitions to `RELEASED`, and for each `ACTIVE` policy a payroll audit is scheduled in `SCHEDULED` status so the final premium can be struck (§3.10).

Cancellation is the mirror image and belongs to a `BrokerAgent`. Cancelling an `ACTIVE` production first requires that no claim on it is `SUBMITTED`, `UNDER_REVIEW`, or `ADJUSTED`; an open claim blocks the cancellation with `ERR_OPEN_CLAIMS_BLOCK_CANCEL`. The cascade is then total: all policies in `BOUND`, `ENDORSED_PENDING`, or `ACTIVE` move to `CANCELLED`; all certificates in `DRAFT` or `ISSUED` move to `VOIDED`; all `ISSUED` cast endorsements move to `REVOKED`; the completion bond, unless it has been `CLAIMED`, moves to `LAPSED`; every travel extension in `REQUESTED`, `APPROVED`, or `ACTIVE` moves to `DENIED`; and posture is recomputed over the wreckage. Cancelling straight out of `DRAFT` carries no preconditions and a single consequence: every `QUOTED` policy moves to `CANCELLED`.

Individual policies obey a smaller version of the same rule. A `BrokerAgent` may cancel a `BOUND` or `ACTIVE` policy only while none of its own claims is `SUBMITTED`, `UNDER_REVIEW`, or `ADJUSTED`, or the refusal is `ERR_OPEN_CLAIMS_BLOCK_POLICY_CANCEL`. Cancelling revokes that policy's endorsements in `DRAFT` or `ISSUED`, and when the cancelled policy was `ACTIVE`, every certificate listing its coverage line is voided; posture is recomputed either way. Policies also end on their own schedule: an `ACTIVE` policy expires automatically once the logical clock reaches its `expiry_date`, but only when no renewal offer for that policy is still `OFFERED` or `ACCEPTED` — and a policy that does expire takes every certificate listing its coverage line with it into `EXPIRED`, recomputing posture again.

### 3.10. Payroll Audits, Final Premiums, and Policy Renewal

Entertainment premiums are written against a declared payroll basis and trued-up afterwards. Audits arrive on a policy in two ways: scheduled automatically at wrap for each `ACTIVE` policy, or created directly by an `ExternalAuditor` or `PlatformOperator` with the audit window as `audit_period_start` and `audit_period_end` (the end strictly after the start), the `auditor_name`, and the `reported_payroll_cents` the auditor found. An audit is born `SCHEDULED`; its list view filters by `status`, and the flat cross-production view also filters by `policy_id`.

The audit lifecycle is a small loop with a fork. Submission — by the `ExternalAuditor` — moves `SCHEDULED` → `SUBMITTED`, requiring the reported payroll to be zero or more and the period end to fall strictly after the period start. A `ProductionManager` who disputes the figures moves a `SUBMITTED` audit to `DISPUTED`, and the auditor resubmits a disputed audit back to `SUBMITTED` with corrected figures. Posting is the financial event: a `BrokerAgent` moves `SUBMITTED` → `POSTED`, which is only possible while the policy itself is `ACTIVE` or `EXPIRED` — audits cannot post against `QUOTED` or `CANCELLED` policies. Posting copies the audit's `reported_payroll_cents` into the policy's `audited_payroll_cents`, recomputes the premium with exactly the same formula as the provisional premium (§3.1) but reading the audited payroll instead of the declared basis — including the same minimum-premium floor — and stores the result as the policy's `final_premium_cents`. The audit then records `premium_delta_cents`, the final premium minus the provisional premium: a positive delta means the production owes the carrier the difference, a negative delta means a refund is due to the production.

Renewal is the other post-term process. An `UnderwriterAgent` creates a renewal offer for a policy by specifying only the `renewal_term_months` — 6, 12, or 18. Creation computes two figures and tidies the deck. The `loss_ratio_pct` summarizes the expiring term: incurred losses are the sum, over the policy's claims in `ADJUSTED`, `SETTLED`, or `CLOSED` whose `occurrence_date` lies inside the policy's effective window, of each claim's `loss_amount_cents` minus its `deductible_applied_cents`; earned premium is the policy's `provisional_premium_cents` — deliberately the provisional figure, since audits are not always complete. When the earned premium is zero the ratio is zero; otherwise the ratio is the incurred losses multiplied by 10000 and divided by the earned premium, rounded half up to a whole number, so a policy with no claims scores 0 and one whose incurred losses exactly equal the earned premium scores 10000, a full 100.00 percent. The `offered_premium_cents` then starts from the prior `provisional_premium_cents` and applies a loading factor keyed to that ratio: below 3000 the factor is 0.90 — a ten percent discount for a clean term; from 3000 up to below 6000 the factor is 1.00; from 6000 up to below 9000 the factor is 1.15; and at 9000 or above the factor is 1.40. The boundary is inclusive at the lower bound of the higher tier: a ratio of exactly 3000 selects 1.00, exactly 6000 selects 1.15, and exactly 9000 selects 1.40. The product is rounded half up to whole cents. Creation also stamps `offer_expires_at` fourteen days after the offer's `created_at`, and any prior `OFFERED` offer for the same policy is automatically superseded, moving to `SUPERSEDED`.

Acceptance rests with the `ProductionManager` and is OCC-guarded: the request must carry `expected_policy_version` matching the policy's current `version`, with a stale view rejected as `ERR_STALE_VERSION` per §2.8. The offer must still be live — once the logical clock reaches `offer_expires_at`, acceptance is refused with `ERR_RENEWAL_OFFER_EXPIRED` and the offer itself ages out to `EXPIRED` automatically. The policy must be `ACTIVE` or `EXPIRED`, and no payroll audit on the policy may be `SCHEDULED` or `SUBMITTED`, or acceptance is blocked with `ERR_AUDIT_PENDING_BLOCKS_RENEWAL`. Acceptance extends the policy's `expiry_date` by the `renewal_term_months`, flips an `EXPIRED` policy back to `ACTIVE`, resets the premium basis by copying `offered_premium_cents` into `provisional_premium_cents`, clears `audited_payroll_cents` and `final_premium_cents` back to null for the new term, and increments the policy's `version`. Declining is the simpler path — `OFFERED` → `DECLINED`, no conditions. The renewal offer list, per policy or across productions, filters by `status` and, on the flat view, by `policy_id`.

## 4. Endpoint Definitions

Endpoints that create a new resource respond with HTTP 201; all other successful operations — reads, list queries, and state-transition actions — respond with HTTP 200. The table below is deliberately minimal: request payloads, response shapes, preconditions, and side effects for each endpoint are defined by the narratives in §2 and §3, and the state-pair framing there (for example `QUOTED` → `BOUND`) identifies the matching row here.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | `/_clock/set_current_utc` | Set the server's logical clock; fires all time-based transitions whose threshold has been crossed | PlatformOperator |
| POST | `/productions` | Create a new production | BrokerAgent |
| GET | `/productions` | List productions with pagination | BrokerAgent, ProductionManager, UnderwriterAgent, ClaimsAdjuster, ClearanceCounsel, SuretyUnderwriter, ExternalAuditor, PlatformOperator |
| GET | `/productions/{id}` | Get a production by id | BrokerAgent, ProductionManager, UnderwriterAgent, ClaimsAdjuster, ClearanceCounsel, SuretyUnderwriter, ExternalAuditor, PlatformOperator |
| POST | `/productions/{id}/activate` | Transition production `DRAFT` → `ACTIVE` | BrokerAgent |
| POST | `/productions/{id}/wrap` | Transition production `ACTIVE` → `WRAPPED` | ProductionManager |
| POST | `/productions/{id}/cancel` | Transition production `DRAFT` or `ACTIVE` → `CANCELLED` | BrokerAgent |
| POST | `/productions/{id}/policies` | Create a policy in `QUOTED` state | BrokerAgent |
| GET | `/productions/{id}/policies` | List policies for a production | BrokerAgent, ProductionManager, UnderwriterAgent, ClaimsAdjuster, ExternalAuditor, PlatformOperator |
| GET | `/productions/{id}/policies/{childId}` | Get a policy | BrokerAgent, ProductionManager, UnderwriterAgent, ClaimsAdjuster, ExternalAuditor, PlatformOperator |
| POST | `/productions/{id}/policies/{childId}/bind` | Bind a `QUOTED` policy (computes the provisional premium) | BrokerAgent |
| POST | `/productions/{id}/policies/{childId}/cancel` | Cancel a `BOUND` or `ACTIVE` policy | BrokerAgent |
| POST | `/productions/{id}/cast-members` | Add a cast member to a production | ProductionManager |
| GET | `/productions/{id}/cast-members` | List cast members | BrokerAgent, ProductionManager, UnderwriterAgent, ClaimsAdjuster, PlatformOperator |
| GET | `/productions/{id}/cast-members/{childId}` | Get a cast member | BrokerAgent, ProductionManager, UnderwriterAgent, PlatformOperator |
| POST | `/productions/{id}/cast-members/{childId}/physical-exam` | Record a physical exam result | UnderwriterAgent |
| POST | `/productions/{id}/cast-members/{childId}/physical-exam-retake` | Reset a `FAILED` exam to `PENDING` for retake | UnderwriterAgent |
| POST | `/productions/{id}/cast-endorsements` | Create a cast endorsement in `DRAFT` | UnderwriterAgent |
| GET | `/productions/{id}/cast-endorsements` | List cast endorsements | BrokerAgent, ProductionManager, UnderwriterAgent, PlatformOperator |
| GET | `/productions/{id}/cast-endorsements/{childId}` | Get a cast endorsement | BrokerAgent, ProductionManager, UnderwriterAgent, PlatformOperator |
| POST | `/productions/{id}/cast-endorsements/{childId}/issue` | Issue a `DRAFT` endorsement | UnderwriterAgent |
| POST | `/productions/{id}/cast-endorsements/{childId}/revoke` | Revoke an endorsement | UnderwriterAgent |
| POST | `/productions/{id}/certificates` | Create a certificate in `DRAFT` | BrokerAgent |
| GET | `/productions/{id}/certificates` | List certificates | BrokerAgent, ProductionManager, PlatformOperator |
| GET | `/productions/{id}/certificates/{childId}` | Get a certificate | BrokerAgent, ProductionManager, PlatformOperator |
| POST | `/productions/{id}/certificates/{childId}/issue` | Issue a `DRAFT` certificate | BrokerAgent |
| POST | `/productions/{id}/certificates/{childId}/void` | Void a certificate | BrokerAgent |
| POST | `/productions/{id}/claims` | Report a new claim | ProductionManager |
| GET | `/productions/{id}/claims` | List claims | BrokerAgent, ProductionManager, ClaimsAdjuster, PlatformOperator |
| GET | `/productions/{id}/claims/{childId}` | Get a claim | BrokerAgent, ProductionManager, ClaimsAdjuster, PlatformOperator |
| POST | `/productions/{id}/claims/{childId}/acknowledge` | Transition claim `SUBMITTED` → `UNDER_REVIEW` | ClaimsAdjuster |
| POST | `/productions/{id}/claims/{childId}/adjust` | Cyclic reserve adjustment, `UNDER_REVIEW` ↔ `ADJUSTED` | ClaimsAdjuster |
| POST | `/productions/{id}/claims/{childId}/deny` | Transition claim `UNDER_REVIEW` or `ADJUSTED` → `DENIED` | ClaimsAdjuster |
| POST | `/productions/{id}/claims/{childId}/settle` | Transition claim `UNDER_REVIEW` or `ADJUSTED` → `SETTLED` | ClaimsAdjuster |
| POST | `/productions/{id}/claims/{childId}/close` | Transition claim `SETTLED` or `DENIED` → `CLOSED` | ClaimsAdjuster |
| GET | `/productions/{id}/claims/{claimId}/events` | List the claim's event log | BrokerAgent, ProductionManager, ClaimsAdjuster, PlatformOperator |
| POST | `/productions/{id}/clearance-items` | Create a clearance item in `PENDING` | ClearanceCounsel |
| GET | `/productions/{id}/clearance-items` | List clearance items | BrokerAgent, ProductionManager, ClearanceCounsel, UnderwriterAgent, PlatformOperator |
| GET | `/productions/{id}/clearance-items/{childId}` | Get a clearance item | BrokerAgent, ProductionManager, ClearanceCounsel, UnderwriterAgent, PlatformOperator |
| POST | `/productions/{id}/clearance-items/{childId}/resolve` | Resolve a clearance item (`CLEARED`, `FLAGGED`, or `WAIVED`) | ClearanceCounsel |
| POST | `/productions/{id}/completion-bond` | Apply for a completion bond (creates in `APPLIED`) | ProductionManager |
| GET | `/productions/{id}/completion-bond` | Get the production's completion bond (returns an array of zero or one) | BrokerAgent, ProductionManager, SuretyUnderwriter, PlatformOperator |
| POST | `/productions/{id}/completion-bond/underwrite` | Underwrite the bond, `APPLIED` → `UNDERWRITTEN` | SuretyUnderwriter |
| POST | `/productions/{id}/completion-bond/issue` | Issue the bond, `UNDERWRITTEN` → `ISSUED` | SuretyUnderwriter |
| POST | `/productions/{id}/completion-bond/claim` | Claim against the bond, `ISSUED` → `CLAIMED` | SuretyUnderwriter |
| POST | `/productions/{id}/completion-bond/lapse` | Lapse the bond, `APPLIED` or `UNDERWRITTEN` → `LAPSED` | SuretyUnderwriter |
| POST | `/productions/{id}/foreign-travel-extensions` | Request a foreign travel extension | ProductionManager |
| GET | `/productions/{id}/foreign-travel-extensions` | List travel extensions | BrokerAgent, ProductionManager, UnderwriterAgent, PlatformOperator |
| GET | `/productions/{id}/foreign-travel-extensions/{childId}` | Get a travel extension | BrokerAgent, ProductionManager, UnderwriterAgent, PlatformOperator |
| POST | `/productions/{id}/foreign-travel-extensions/{childId}/approve` | Transition extension `REQUESTED` → `APPROVED` | UnderwriterAgent |
| POST | `/productions/{id}/foreign-travel-extensions/{childId}/deny` | Transition extension `REQUESTED` or `APPROVED` → `DENIED` | UnderwriterAgent |
| POST | `/productions/{id}/policies/{pid}/payroll-audits` | Schedule a payroll audit | ExternalAuditor, PlatformOperator |
| GET | `/productions/{id}/policies/{pid}/payroll-audits` | List payroll audits for a policy | BrokerAgent, ProductionManager, ExternalAuditor, PlatformOperator |
| GET | `/productions/{id}/policies/{pid}/payroll-audits/{childId}` | Get a payroll audit | BrokerAgent, ProductionManager, ExternalAuditor, PlatformOperator |
| POST | `/productions/{id}/policies/{pid}/payroll-audits/{childId}/submit` | Transition audit `SCHEDULED` or `DISPUTED` → `SUBMITTED` | ExternalAuditor |
| POST | `/productions/{id}/policies/{pid}/payroll-audits/{childId}/post` | Post the audit, `SUBMITTED` → `POSTED`; computes final premium and delta | BrokerAgent |
| POST | `/productions/{id}/policies/{pid}/payroll-audits/{childId}/dispute` | Transition audit `SUBMITTED` → `DISPUTED` | ProductionManager |
| POST | `/productions/{id}/policies/{pid}/renewal-offers` | Create a renewal offer; supersedes any prior `OFFERED` offer for the policy | UnderwriterAgent |
| GET | `/productions/{id}/policies/{pid}/renewal-offers` | List renewal offers | BrokerAgent, ProductionManager, UnderwriterAgent, PlatformOperator |
| GET | `/productions/{id}/policies/{pid}/renewal-offers/{childId}` | Get a renewal offer | BrokerAgent, ProductionManager, UnderwriterAgent, PlatformOperator |
| POST | `/productions/{id}/policies/{pid}/renewal-offers/{childId}/accept` | Accept a renewal offer | ProductionManager |
| POST | `/productions/{id}/policies/{pid}/renewal-offers/{childId}/decline` | Decline a renewal offer | ProductionManager |
| GET | `/cast-endorsements` | List cast endorsements across productions, filterable by cast member or policy | BrokerAgent, ProductionManager, UnderwriterAgent, PlatformOperator |
| GET | `/cast-endorsements/{id}` | Get a cast endorsement by id | BrokerAgent, ProductionManager, UnderwriterAgent, PlatformOperator |
| GET | `/claims` | List claims across productions, filterable by policy | BrokerAgent, ProductionManager, ClaimsAdjuster, PlatformOperator |
| GET | `/claims/{id}` | Get a claim by id | BrokerAgent, ProductionManager, ClaimsAdjuster, PlatformOperator |
| GET | `/claim-events` | List claim events across productions, filterable by claim | BrokerAgent, ProductionManager, ClaimsAdjuster, PlatformOperator |
| GET | `/claim-events/{id}` | Get a claim event by id | BrokerAgent, ProductionManager, ClaimsAdjuster, PlatformOperator |
| GET | `/payroll-audits` | List payroll audits across productions, filterable by policy | BrokerAgent, ProductionManager, ExternalAuditor, PlatformOperator |
| GET | `/payroll-audits/{id}` | Get a payroll audit by id | BrokerAgent, ProductionManager, ExternalAuditor, PlatformOperator |
| GET | `/renewal-offers` | List renewal offers across productions, filterable by policy | BrokerAgent, ProductionManager, UnderwriterAgent, PlatformOperator |
| GET | `/renewal-offers/{id}` | Get a renewal offer by id | BrokerAgent, ProductionManager, UnderwriterAgent, PlatformOperator |

## 5. Error Code Catalogue

The catalogue below lists every error identifier and its HTTP status. Trigger conditions are intentionally not repeated here — they are defined in the validation pipeline of §2.9 and in the workflow narratives of §3, next to the operations they guard.

| Error ID | HTTP Status Code |
|---|---|
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_SELF_SETTLEMENT_FORBIDDEN` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_DUPLICATE_IDENTIFIER` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_INVALID_ENUM` | 400 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_ADDITIONAL_INSURED_REQUIRED` | 400 |
| `ERR_TEMPORAL_RANGE_INVALID` | 422 |
| `ERR_CERT_WINDOW_OUTSIDE_POLICY` | 422 |
| `ERR_WINDOW_ELAPSED` | 422 |
| `ERR_FOREIGN_TRAVEL_OVERLAP` | 422 |
| `ERR_POSTURE_BLOCKS_ISSUANCE` | 422 |
| `ERR_POSTURE_BLOCKS_BOND` | 422 |
| `ERR_POSTURE_BLOCKS_FOREIGN` | 422 |
| `ERR_COVERAGE_LINE_NOT_BOUND` | 422 |
| `ERR_CAST_ENDORSEMENT_INVALID` | 422 |
| `ERR_CAST_ENDORSEMENT_MISSING` | 422 |
| `ERR_CAST_EXAM_INCOMPLETE` | 422 |
| `ERR_EO_CLEARANCE_INCOMPLETE` | 422 |
| `ERR_GL_PREREQUISITE_MISSING` | 422 |
| `ERR_NO_BOUND_POLICY` | 422 |
| `ERR_BOND_NOT_ISSUED` | 422 |
| `ERR_MANDATORY_CLEARANCE_OPEN` | 422 |
| `ERR_OPEN_CLAIMS_BLOCK_WRAP` | 422 |
| `ERR_OPEN_CLAIMS_BLOCK_CANCEL` | 422 |
| `ERR_OPEN_CLAIMS_BLOCK_POLICY_CANCEL` | 422 |
| `ERR_DRAFT_CERTIFICATES_OPEN` | 422 |
| `ERR_POLICY_NOT_CLAIMABLE` | 422 |
| `ERR_REFERENCED_STATE_INVALID` | 422 |
| `ERR_SETTLEMENT_EXCEEDS_RESERVE` | 422 |
| `ERR_FISCAL_CONSTRAINT_VIOLATED` | 422 |
| `ERR_DEDUCTIBLE_CAP_EXCEEDED` | 422 |
| `ERR_AUDIT_PENDING_BLOCKS_RENEWAL` | 422 |
| `ERR_RENEWAL_OFFER_EXPIRED` | 422 |
