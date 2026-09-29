# HERS Rating & Code Compliance API — Product Requirements Document

## 1. Introduction

A RESNET-accredited rating provider sits between three parties that rarely agree: production and custom home builders who want incentive paperwork issued quickly, code officials who need defensible evidence that each dwelling meets the energy code edition their jurisdiction adopted, and a national registry that will reject any rating file whose numbers do not hold together. The provider's own accreditation depends on proving that its certified raters and rating field inspectors are being quality-assurance sampled at the required rate, that sampled subdivisions were sampled lawfully, and that every dollar of tax-credit or utility-program money it certified is traceable to a confirmed, as-built measurement. This API is the system of record for that entire chain of custody.

Two rating numbers exist for every home and they are deliberately not the same number. The **projected rating** is computed from a plan model's paper design values before a shovel breaks ground; the **confirmed rating** is computed from blower-door and duct-leakage instrument readings taken at the final as-built checkpoint. The gap between them is where builders lose incentive money and where quality-assurance findings originate, so the system must keep both, must never let a later plan edit move a rating that has already been opened, and must be able to unwind a certified incentive completely when a quality-assurance review or a registry dispute invalidates the file behind it.

The requirements below describe a compliance workflow with four simultaneous, independent state dimensions on every rating file — where it stands in the field-verification workflow, whether it satisfies a code-compliance path, whether it has survived quality-assurance review, and where it sits with the registry — plus a sampling protocol that lets one tested home carry a group of its siblings, and cascades that tear that arrangement down when trust is lost. Money ledgers and home-coverage ledgers in this system are **conserved quantities**: every operation that moves them has a compensating counterpart, and after the pair has run the ledger must read exactly what it read before.

## 2. Global Specifications & System-Wide Principles

This section defines the contracts, envelopes and cross-cutting principles that hold for every endpoint in the API. Where §3 describes what a workflow means, this section describes the invariants that workflow may never violate.

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which that user is acting. Five roles exist and their spellings are exact: `RatingProviderAdmin`, `CertifiedRater`, `FieldInspector`, `QADesignee`, and `BuilderRep`. If `X-User-Role` is absent or is not one of those five strings, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). `X-User-ID` is likewise mandatory for the four identity-bearing roles, and its absence is the same `ERR_UNAUTHENTICATED` rejection; it may be omitted only when `X-User-Role` is `RatingProviderAdmin`. Once authentication succeeds, the acting role must appear on the authorization list of the endpoint being called (see §4); a role calling an endpoint it is not listed on is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403).

The five roles differ in how `X-User-ID` is interpreted, and that difference is what makes ownership enforceable:

- When `X-User-Role` is `RatingProviderAdmin`, `X-User-ID` is an opaque operator identifier that is not tied to any persisted entity. The server may accept and log it, but it never compares it to any resource's `id`, and provider staff therefore act on any builder's, any rater's and any home's records. `RatingProviderAdmin` is the provider's own back office: it onboards builders, subdivisions and certified people, drives the sampling protocol's selection and closure steps, assigns quality-assurance reviews, records registry decisions, adjudicates builder corrective actions, issues documentation packages, and drives the logical clock.
- When `X-User-Role` is `CertifiedRater`, `X-User-ID` is the `id` of the acting `Rater` row. Ownership checks compare the resource's rater foreign key to `X-User-ID`: a rating may only be confirmed or submitted to the registry by the rater whose `rater_id` the rating carries.
- When `X-User-Role` is `FieldInspector`, `X-User-ID` is the `id` of the acting `Rater` row. Ownership checks compare an inspection's `inspector_id` to `X-User-ID`: measurements may only be recorded, and a checkpoint may only be closed, by the person the checkpoint was scheduled for.
- When `X-User-Role` is `QADesignee`, `X-User-ID` is the `id` of the acting `Rater` row. Ownership checks compare a quality-assurance review's `reviewer_id` to `X-User-ID`: only the assigned designee may record that review's outcome.
- When `X-User-Role` is `BuilderRep`, `X-User-ID` is the `id` of the acting `Builder` row. Ownership checks resolve the target resource up through the home and its subdivision to the owning builder and compare that builder's `id` to `X-User-ID`: a builder representative registers lots only in its own subdivisions, answers only corrective actions raised against its own ratings, and drafts documentation packages only against its own homes' ratings.

An identity-bearing actor that operates on a resource which does not resolve to its own `X-User-ID` is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403). Note that the three certified roles are all backed by the same `Rater` table: which of them a person may legitimately act as is governed by that person's `cert_level`, described in §2.11.

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

Every list endpoint accepts two optional query parameters. `limit` caps the number of rows returned; it defaults to 10, its minimum accepted value is 1 and its maximum accepted value is 100. `offset` skips a number of leading rows and defaults to 0; its minimum accepted value is 0. A `limit` outside the range 1 through 100 inclusive, or a negative `offset`, is a request-shape failure and is rejected with `ERR_INVALID_REQUEST` (HTTP 422).

Unless a specific list endpoint states otherwise, results are ordered by the resource's `created_at` timestamp in ascending order — oldest first. List responses carry `limit`, `offset`, `total_count` and `has_more` inside the `meta` object of the envelope, where `total_count` reports the number of rows matching the filters before pagination is applied and `has_more` reports whether any matching row remains beyond the returned page.

### 2.4. Common Resource Properties

Every persisted resource carries a server-minted `id`, formatted as a UUID with no type prefix of any kind, and a `created_at` timestamp expressed as an ISO 8601 UTC instant with three fractional digits (for example `2026-08-01T00:00:00.000Z`). Clients never supply an `id`.

`Builder`, `Subdivision`, `PlanModel`, `Home`, `Rater`, `Rating`, `Inspection`, `SampleSet`, `QAReview`, `CorrectiveAction` and `DocumentPackage` additionally carry `updated_at` — an ISO 8601 UTC timestamp refreshed on every mutation of that row — and `version`, an integer that starts at 1 on creation and increases by exactly 1 on every mutation of that row. This applies to *derived* mutations as well: when a builder's money ledger moves because a package elsewhere in the graph was issued, when a subdivision's coverage counters move because a home joined a sample set, or when a rating's compliance dimension is rewritten by a sample-set closure, the affected row's `updated_at` is refreshed and its `version` is incremented even though no client addressed that row directly.

`DiagnosticTest` is the one exception. A recorded measurement is append-only evidence: it carries `id` and `created_at` only, and both `updated_at` and `version` are absent from it. A diagnostic test is never edited, never re-graded and never deleted once written.

### 2.5. The Logical Clock

The server does not read wall-clock time. It maintains a single **logical clock** which, before any client sets it, reads exactly `2026-08-01T00:00:00Z`, and it never falls back to real time. Everything time-derived in this system reads that clock: a rater's effective certification status, a diagnostic test's `performed_at_utc`, a rating's `confirmed_at`, and a documentation package's `issued_at`. A `RatingProviderAdmin` may move the clock by supplying `to_iso8601`; the response reports the new `current_utc`. Moving the clock immediately re-derives every rater's `effective_certification_status` against the new instant, so advancing time past a certification expiry is sufficient to disable that person without touching their row.

### 2.6. Numeric Precision and Rounding Discipline

All arithmetic in this system is exact decimal arithmetic. Binary floating-point accumulation is not acceptable, because several of the thresholds in §2.7 are decided at an exact boundary and a one-unit-in-the-last-place drift flips a pass into a failure.

Three rounding rules govern the whole API and they differ from one another on purpose:

- **Normalized measurements** — a diagnostic test's `normalized_value` — are rounded half-up to exactly 2 decimal places, and the rounding happens *before* the threshold comparison. A reading that normalizes to 3.00 therefore passes a limit of 3.0, and a reading that normalizes to 3.01 fails it.
- **HERS index values** — `projected_index`, `confirmed_index`, `submitted_index`, `representative_index` and `eri_target` — are integers. The index computation keeps full exact-decimal precision through every intermediate value and rounds exactly once, half-up, to 0 decimal places at the very end, after the photovoltaic credit has been subtracted. There is no intermediate rounding anywhere in that chain.
- **Money** is held in integer cents throughout: `utility_program_budget_cents`, `certified_incentive_cents`, `provisional_amount_cents`, `certified_amount_cents` and the `amount_cents` inside each line item are all whole numbers of cents. Where a rate produces a fractional cent, the rounding is half-up to whole cents, and §3.9 pins exactly where in the sum that rounding happens.

Counters — `homes_count`, `sampled_home_count`, `unsampled_home_count`, `member_count`, `tested_member_count`, `represented_member_count`, `failed_test_count`, `qa_failure_count`, `confirmed_rating_count`, `qa_completed_count`, `qa_files_owed`, `open_corrective_action_count`, `revoked_package_count` and `attempt_count` — are non-negative integers and are never rounded.

### 2.7. Code Edition and Climate Zone Reference Tables

Every subdivision fixes two jurisdictional facts at creation: `code_edition`, which is either `IECC_2015` or `IECC_2021`, and `climate_zone`, which is one of `CZ2`, `CZ3`, `CZ4`, `CZ5` or `CZ6`. Together they select four things — the envelope load factor used by the index calculation, the airtightness limit, the ERI target, and the photovoltaic index-credit cap.

The **envelope load factor** depends on climate zone alone: 0.90 in `CZ2`, 0.95 in `CZ3`, 1.00 in `CZ4`, 1.10 in `CZ5`, and 1.20 in `CZ6`.

The **maximum permitted air changes per hour at 50 pascals** depends on both, and the two editions differ only in zone `CZ3`:

| Code edition | `CZ2` | `CZ3` | `CZ4` | `CZ5` | `CZ6` |
| --- | --- | --- | --- | --- | --- |
| `IECC_2015` | 5.0 | 3.0 | 3.0 | 3.0 | 3.0 |
| `IECC_2021` | 5.0 | 5.0 | 3.0 | 3.0 | 3.0 |

The **ERI target** — the index a home must not exceed to pass on the index-based path — is materially tighter in the newer edition:

| Code edition | `CZ2` | `CZ3` | `CZ4` | `CZ5` | `CZ6` |
| --- | --- | --- | --- | --- | --- |
| `IECC_2015` | 65 | 65 | 65 | 69 | 69 |
| `IECC_2021` | 52 | 53 | 55 | 55 | 54 |

The **photovoltaic index-credit cap** depends on code edition alone. Under `IECC_2021` on-site generation may buy down at most 5.0 index points. Under `IECC_2015` the cap is 100.0 points, which in practice means the credit is uncapped for any realistic array.

The **total duct leakage limit at the final checkpoint** is 4.0 CFM25 per 100 square feet of conditioned floor area regardless of edition or zone. At the rough-in checkpoint the limit depends on whether the air handler was already installed when the test was run: 4.0 with the air handler in place, and the tighter 3.0 without it.

### 2.8. Validation Ordering

Requests are validated in a fixed, globally consistent order, and the **first** failing check determines the response. This ordering is normative: when two checks would both fail on the same request, the lower-numbered one is the error the client sees. Implementations that reorder these checks will report the wrong error for a large class of requests.

1. Authentication of the two context headers, as described in §2.1 — `ERR_UNAUTHENTICATED`, 401. Applies to every endpoint.
2. Role authorization against the called endpoint's role list — `ERR_FORBIDDEN_ROLE`, 403. Applies to every endpoint.
3. Request-shape validation, performed before any database read: all required input fields present, all types correct, all enum members recognized, and all numeric and ordering constraints honoured — `conditioned_floor_area_sqft` and `conditioned_volume_cuft` and `envelope_ua_btu_per_hr_f` and `design_ach50` strictly greater than zero, `bedrooms` at least 1, `hvac_efficiency_index` between 1 and 20 inclusive, `pv_capacity_kw_dc` and `design_duct_leakage_cfm25_per_100sqft` and `measured_value` and `utility_program_budget_cents` at least zero, `scheduled_end_utc` strictly after `scheduled_start_utc`, `window_end_date` on or after `window_start_date`, `limit` within 1 through 100, `offset` at least zero. Any violation is `ERR_INVALID_REQUEST`, 422. Applies to every endpoint.
4. Existence of every identifier in the URL path, validated strictly left to right, so the leftmost missing identifier is the one reported. Each resource has its own not-found code: `ERR_BUILDER_NOT_FOUND`, `ERR_SUBDIVISION_NOT_FOUND`, `ERR_PLAN_MODEL_NOT_FOUND`, `ERR_HOME_NOT_FOUND`, `ERR_RATER_NOT_FOUND`, `ERR_RATING_NOT_FOUND`, `ERR_INSPECTION_NOT_FOUND`, `ERR_SAMPLE_SET_NOT_FOUND`, `ERR_QA_REVIEW_NOT_FOUND`, `ERR_CORRECTIVE_ACTION_NOT_FOUND` and `ERR_DOCUMENT_PACKAGE_NOT_FOUND`, all HTTP 404. Applies to every endpoint whose path carries an identifier. In a two-segment path such as `POST /sample-sets/{id}/homes/{home_id}/withdraw`, a missing sample set is reported before the system looks for the home at all; and a `home_id` that exists but is not a member of that set is also reported as `ERR_HOME_NOT_FOUND`.
5. Existence of every foreign-key identifier in the request body, validated in the order the endpoint declares its inputs, yielding the same resource-specific 404 codes as step 4. This step applies to `POST /subdivisions`, `POST /plan-models`, `POST /homes`, `POST /ratings`, `POST /inspections`, `POST /sample-sets`, `POST /sample-sets/{id}/homes`, `POST /qa-reviews` and `POST /document-packages`.
6. Ownership, for the four identity-bearing roles, exactly as §2.1 defines it — `ERR_NOT_RESOURCE_OWNER`, 403. This step applies to `POST /ratings/{id}/confirm`, `POST /ratings/{id}/submit-to-registry`, `POST /inspections/{id}/tests`, `POST /inspections/{id}/complete`, `POST /qa-reviews/{id}/complete`, `POST /corrective-actions/{id}/submit`, `POST /document-packages` and `POST /homes`.
7. General state admissibility: the target resource is in a state from which the requested transition is defined, and the transition's own preconditions hold — `ERR_INVALID_STATE`, 409. Applies to every action endpoint. The rating-void and file-lock conditions are deliberately *not* folded into this check; they are steps 8 and 9.
8. The rating reached from the target resource is not voided — `ERR_RATING_VOID`, 409. This step applies to `POST /inspections`, `POST /inspections/{id}/tests`, `POST /inspections/{id}/complete`, `POST /ratings/{id}/confirm`, `POST /ratings/{id}/submit-to-registry`, `POST /qa-reviews`, `POST /corrective-actions/{id}/submit`, `POST /document-packages` and `POST /document-packages/{id}/issue`.
9. The rating reached from the target resource is not file-locked — `ERR_RATING_FILE_LOCKED`, 409. This step applies to exactly five endpoints: `POST /inspections`, `POST /inspections/{id}/tests`, `POST /inspections/{id}/complete`, `POST /ratings/{id}/confirm` and `POST /ratings/{id}/submit-to-registry`. It is deliberately **not** applied to `POST /document-packages` or `POST /document-packages/{id}/issue`, because documentation packages are precisely the artefact one produces from a locked, registered file.
10. The stale-rating-version guard on `POST /document-packages` — `ERR_STALE_RATING_VERSION`, 412. See §2.9.
11. The stale-sample-set-version guard on `POST /sample-sets/{id}/homes` and `POST /sample-sets/{id}/homes/{home_id}/withdraw` — `ERR_STALE_SAMPLE_SET_VERSION`, 412. See §2.9.
12. Certification validity of every rater the operation depends on — `ERR_CERTIFICATION_INVALID`, 422. See §2.11. Applies to `POST /ratings`, `POST /ratings/{id}/confirm`, `POST /ratings/{id}/submit-to-registry`, `POST /inspections`, `POST /inspections/{id}/tests`, `POST /inspections/{id}/complete`, `POST /qa-reviews`, `POST /qa-reviews/{id}/complete`, `POST /sample-sets` and `POST /sample-sets/{id}/homes`.
13. Certification *level* suitability for the operation — `ERR_CERT_LEVEL_INSUFFICIENT`, 422. See §2.11. Applies to `POST /ratings`, `POST /ratings/{id}/confirm`, `POST /ratings/{id}/submit-to-registry`, `POST /inspections`, `POST /inspections/{id}/tests`, `POST /qa-reviews/{id}/complete`, `POST /sample-sets` and `POST /sample-sets/{id}/homes`.
14. Segregation of duties — `ERR_SEGREGATION_OF_DUTIES`, 422. Applies to `POST /qa-reviews` and `POST /qa-reviews/{id}/complete`.
15. Plan-model coherence — `ERR_PLAN_MODEL_MISMATCH`, 422. Applies to `POST /homes` and `POST /ratings`.
16. Sample-set/home subdivision coherence — `ERR_HOME_SUBDIVISION_MISMATCH`, 422. Applies to `POST /sample-sets/{id}/homes`.
17. Presence of the checkpoint's mandatory governing tests — `ERR_MISSING_GOVERNING_TEST`, 409. Applies to `POST /ratings/{id}/confirm` and `POST /inspections/{id}/complete`.
18. A home already flagged for individual testing may neither join a sample set nor be picked as its tested home — `ERR_REPRESENTED_HOME_NOT_TESTABLE`, 422. Applies to `POST /sample-sets/{id}/homes` and `POST /sample-sets/{id}/select`.
19. Lot-number uniqueness within the subdivision — `ERR_DUPLICATE_LOT_NUMBER`, 409. Applies to `POST /homes`.
20. Plan-code uniqueness within the subdivision — `ERR_DUPLICATE_PLAN_CODE`, 409. Applies to `POST /plan-models`.
21. At most one live rating per home — `ERR_DUPLICATE_ACTIVE_RATING`, 409. Applies to `POST /ratings`.
22. The subdivision permits sampling — `ERR_SAMPLING_NOT_ENABLED`, 422. Applies to `POST /sample-sets`, `POST /sample-sets/{id}/homes` and `POST /sample-sets/{id}/select`.
23. The home is not already in some sample set — `ERR_HOME_ALREADY_SAMPLED`, 409. Applies to `POST /sample-sets/{id}/homes`.
24. The home's permit date lies inside the set's window — `ERR_HOME_PERMIT_OUTSIDE_WINDOW`, 422. Applies to `POST /sample-sets/{id}/homes`.
25. Membership size bounds — `ERR_SAMPLE_SET_SIZE_INVALID`, 422. Applies to `POST /sample-sets/{id}/homes` and `POST /sample-sets/{id}/select`.
26. The builder is sampling-eligible — `ERR_BUILDER_SAMPLING_INELIGIBLE`, 422. Applies to `POST /sample-sets` and `POST /sample-sets/{id}/select`.
27. The tested-home selector found at least one candidate — `ERR_NO_ELIGIBLE_SAMPLE_HOME`, 422. Applies to `POST /sample-sets/{id}/select`.
28. The closure can be routed because a tested home with a confirmed rating exists — `ERR_SAMPLE_SET_NO_TESTED_RATING`, 409. Applies to `POST /sample-sets/{id}/close`.
29. Compliance and quality-assurance standing — `ERR_RATING_NOT_COMPLIANT`, 422. Applies to `POST /ratings/{id}/submit-to-registry` and `POST /document-packages/{id}/issue`.
30. No unresolved corrective action on the rating — `ERR_OPEN_CORRECTIVE_ACTION`, 409. Applies to `POST /ratings/{id}/submit-to-registry` and `POST /document-packages/{id}/issue`.
31. The submitting rater carries no quality-assurance deficit — `ERR_RATER_QA_DEFICIT`, 422. Applies to `POST /ratings/{id}/submit-to-registry`.
32. Package eligibility by confirmed index — `ERR_PACKAGE_NOT_ELIGIBLE`, 422. Applies to `POST /document-packages/{id}/issue`.
33. The inspector's travel-buffered window is free — `ERR_INSPECTOR_WINDOW_CONFLICT`, 409. Applies to `POST /inspections`.
34. The subdivision has no overlapping live sampling window — `ERR_SAMPLE_WINDOW_CONFLICT`, 409. Applies to `POST /sample-sets`.
35. The builder's utility-program budget accommodates the issuance — `ERR_PROGRAM_BUDGET_EXCEEDED`, 422. Applies to `POST /document-packages/{id}/issue`.

### 2.9. Stale-Version Guards on Drafting and Sample Membership

Three write operations require the client to prove that its view of a parent record is current. Each takes a mandatory version field — it is not optional, and omitting it is an `ERR_INVALID_REQUEST` request-shape failure — carrying the `version` the client last observed on the parent row. No other endpoint in this API accepts a version field.

`POST /document-packages` requires `expected_rating_version` matching the current `version` of the `Rating` named by `rating_id`. If the rating's `version` has advanced since the client last read it, the draft is rejected with `ERR_STALE_RATING_VERSION` (HTTP 412). Drafting is otherwise a perfectly legal act — a fresh draft legitimately supersedes an earlier draft of the same `package_type` — so nothing else in the pipeline would stop a client holding an outdated view of the rating's confirmed index from drafting a package against numbers that have since moved. A successful draft itself increases the rating's `version` by 1, which means a client wishing to draft twice in a row must re-read the rating in between.

`POST /sample-sets/{id}/homes` requires `expected_sample_set_version` matching the target `SampleSet`'s current `version`; a mismatch is `ERR_STALE_SAMPLE_SET_VERSION` (HTTP 412). Additions are legal from the forming state and read no status field that a previous addition altered, so without this guard a client whose view of `member_count` was stale could push a set past its seven-member cap. A successful addition increases the set's `version` by 1.

`POST /sample-sets/{id}/homes/{home_id}/withdraw` requires `expected_sample_set_version` matching the target `SampleSet`'s current `version`; a mismatch is again `ERR_STALE_SAMPLE_SET_VERSION` (HTTP 412). Withdrawal is legal from the forming state for any member, so a client acting on a stale membership roster would otherwise silently shrink a set that someone else had just re-shaped. A successful withdrawal likewise increases the set's `version` by 1.

### 2.10. Conserved Ledgers and Cascade Integrity

Two quantities in this system are conserved, meaning that a mutating operation and its compensating counterpart must together leave the quantity exactly as it was.

The **builder money ledger** is `certified_incentive_cents` on `Builder`. It is defined as the sum of `certified_amount_cents` over every `DocumentPackage` that is currently issued and reachable from that builder through the chain package → rating → home → subdivision → builder. Drafted, superseded and revoked packages each contribute zero. The ledger is recomputed as a full aggregation rather than patched blindly, and the governing invariant is that issuing a package and then revoking it restores `certified_incentive_cents` to exactly its pre-issuance value. Alongside it, `revoked_package_count` counts the revoked packages reachable from that builder.

The **home coverage ledger** lives on `Subdivision`. `homes_count` is the number of homes whose `subdivision_id` is that subdivision; `sampled_home_count` is the number of those homes whose `sample_set_id` is not null; and `unsampled_home_count` is `homes_count` less `sampled_home_count`. Membership is always read from the home's own `sample_set_id`, never from a sample set's `member_count`. The invariant is that after every single operation the sampled and unsampled counts sum to `homes_count`, and that adding a home to a set and then withdrawing it restores all three counters to their pre-addition values.

Cascades are the third integrity concern, and they are multi-hop by design. A quality-assurance major failure, a sample-set failure, and a rating void each start a chain that walks *outward* from the rating to sibling entities — revoking issued packages, moving the money ledger back, suspending the builder, voiding sampling arrangements, releasing member homes, archiving plan models, and opening corrective actions. Every hop of every cascade is mandatory and runs in the same request as the operation that triggered it: there is no deferred or eventual reconciliation anywhere in this API. Each row a cascade touches has its `updated_at` refreshed and its `version` incremented. §3.5, §3.6 and §3.8 spell out the hops.

### 2.11. Certification Standing and Segregation of Duties

Every certified person is a `Rater` row created by provider staff from a `full_name`, a `cert_level` that is one of `RATER`, `RATING_FIELD_INSPECTOR` or `QA_DESIGNEE`, and a `cert_expires_at` instant. A newly certified person starts with `certification_status` of `ACTIVE`, an `effective_certification_status` derived immediately against the logical clock, `qa_failure_count`, `confirmed_rating_count`, `qa_completed_count` and `qa_files_owed` all at zero, and `registry_hold` false. Two status fields describe standing. `certification_status` is the disciplinary state and is one of `ACTIVE`, `PROBATION` or `SUSPENDED`. `effective_certification_status` is the field every gate in the system actually reads: it equals `certification_status` except that it reports `EXPIRED` whenever the logical clock stands at or after `cert_expires_at`. Its value is therefore one of `ACTIVE`, `PROBATION`, `SUSPENDED` or `EXPIRED`.

An operation may only proceed if every rater it depends on has an `effective_certification_status` of either `ACTIVE` or `PROBATION`. A person who is suspended, or whose certification has expired, blocks the operation with `ERR_CERTIFICATION_INVALID` (HTTP 422). "Every rater the operation depends on" is not only the acting user: scheduling a checkpoint depends on the named `inspector_id`, opening a rating depends on the named `rater_id`, and confirming depends on the rating's rater of record.

Beyond standing, the person's `cert_level` must suit the act. Only a `RATER` may register plan models, open ratings, confirm ratings, submit files to the registry, open sample sets and manage sample-set membership. Inspections and diagnostic measurements may be performed by a `RATING_FIELD_INSPECTOR` or by a `RATER`. Only a `QA_DESIGNEE` may record a quality-assurance outcome. A mismatch — a rating field inspector attempting a confirmation, or a rater attempting to close out a quality-assurance review — is rejected with `ERR_CERT_LEVEL_INSUFFICIENT` (HTTP 422).

Segregation of duties is a separate and stricter rule. A quality-assurance review may never be assigned to, nor completed by, the rating's own rater of record: the review's `reviewer_id` must differ from the rating's `rater_id`. For a field re-inspection, the reviewer must additionally not be the inspector who performed the governing final checkpoint on that rating. Either violation yields `ERR_SEGREGATION_OF_DUTIES` (HTTP 422), and it is checked both when the review is assigned and again when its outcome is recorded.

## 3. Business Logic & Workflows

### 3.1. Onboarding Builders, Subdivisions and Plan Models

Provider staff open the relationship by registering the builder client. A builder is created with a `name`, a `builder_type` that is either `PRODUCTION` or `CUSTOM`, and a `utility_program_budget_cents` figure representing the total utility-program incentive money, in whole cents, that this builder is permitted to have certified across all of its documentation packages at any one time. A newly registered builder has `status` of `ACTIVE`, and its four derived numbers — `open_corrective_action_count`, `revoked_package_count`, `certified_incentive_cents` and the `sampling_eligible` flag — are computed immediately, which for a brand-new builder means `open_corrective_action_count`, `revoked_package_count` and `certified_incentive_cents` all read zero. `status` has only two possible values, `ACTIVE` and `SAMPLING_SUSPENDED`.

`sampling_eligible` is the gate that decides whether this builder may use the sampling protocol at all, and it is a derived boolean, never an input. It is true when, and only when, all three of the following hold: `builder_type` is `PRODUCTION`, `status` is `ACTIVE`, and `open_corrective_action_count` is zero. A custom builder therefore never becomes sampling-eligible no matter how clean its record; a production builder loses eligibility the moment a single corrective action is opened anywhere in its portfolio, and regains it when that action is resolved. `open_corrective_action_count` counts the corrective actions in `OPEN`, `SUBMITTED` or `ESCALATED` status whose rating belongs, by way of its home, to one of this builder's subdivisions — note that a rejected corrective action is deliberately excluded from that count even though §3.7 still treats it as unresolved for other purposes.

Under a builder, provider staff open subdivisions. A subdivision is created against a `builder_id` with a `name`, a `code_edition`, a `climate_zone`, and two optional elections. `sampling_enabled` says whether the sampling protocol may be used in this subdivision and defaults to `false` when omitted. `compliance_path_preference` is the binding code-compliance path election for every rating in the subdivision; it is either `ERI_PATH` or `PRESCRIPTIVE_PATH` and defaults to `ERI_PATH`. This election is binding in the strong sense: a subdivision that elects `PRESCRIPTIVE_PATH` forgoes any index-based path entirely, as §3.4 describes. On creation the subdivision's coverage ledger — `homes_count`, `sampled_home_count` and `unsampled_home_count` — starts at zero across the board. Subdivisions can be listed, and that list optionally filters on `builder_id`.

A certified rater then registers the **plan models** the builder offers in that subdivision. A plan model is created against a `subdivision_id` and carries a `plan_code` that must be unique within its subdivision — a collision is rejected with `ERR_DUPLICATE_PLAN_CODE`. Its physical description is the conditioned floor area in square feet (`conditioned_floor_area_sqft`), the conditioned volume in cubic feet (`conditioned_volume_cuft`), the `bedrooms` count, the design envelope conductance in BTU per hour per degree Fahrenheit (`envelope_ua_btu_per_hr_f`), the design airtightness `design_ach50` expressed as air changes per hour at 50 pascals, the design total duct leakage `design_duct_leakage_cfm25_per_100sqft` expressed in CFM25 per 100 square feet of conditioned floor area, an `hvac_efficiency_index` between 1 and 20 inclusive where higher is better, and an optional on-site photovoltaic DC capacity `pv_capacity_kw_dc` in kilowatts which defaults to 0 when omitted. Registration computes the plan's `projected_index` on the spot and sets `status` to `ACTIVE`; the only other value `status` can ever take is `ARCHIVED`, which a cascade described in §3.6 writes.

**Computing a HERS index.** The index calculation is a single routine with two variants, and both variants run against exactly one plan model plus the `climate_zone` and `code_edition` of that plan's subdivision. There is no aggregation over other homes, other plans or other ratings. The routine proceeds as follows.

First the **base load** is assembled from three additive terms. The first term is the plan's `envelope_ua_btu_per_hr_f` multiplied by the envelope load factor for the subdivision's climate zone from §2.7. The second term is 0.60 multiplied by the airtightness figure, multiplied by the plan's `conditioned_volume_cuft`, and divided by 1000. The third term is 0.90 multiplied by the duct leakage figure, multiplied by the plan's `conditioned_floor_area_sqft`, and divided by 100.

Second, an **equipment multiplier** is derived from the plan's `hvac_efficiency_index`: take 1.35, subtract 0.05 multiplied by the efficiency index, then clamp the result into the closed range from 0.62 to 1.05 — that is, any value above 1.05 becomes exactly 1.05 and any value below 0.62 becomes exactly 0.62. Because the efficiency index is capped at 20, the lower clamp is genuinely reachable, and because it starts at 1, so is the upper one.

Third, a **reference load** is computed as 0.30 multiplied by the plan's `conditioned_floor_area_sqft`, plus 40.0 multiplied by the plan's `bedrooms`.

Fourth, the **raw index** is the base load multiplied by the equipment multiplier, divided by the reference load, and then multiplied by 100.

Fifth, the **photovoltaic credit** is the smaller of two quantities: the photovoltaic index-credit cap for the subdivision's code edition from §2.7, and 4.0 index points for each kilowatt of `pv_capacity_kw_dc`. A plan with no array therefore earns no credit, and under the newer edition a plan with any array larger than 1.25 kilowatts is held at the 5.0-point cap.

Finally the raw index has the photovoltaic credit subtracted from it, that difference is rounded half-up to a whole number, and the result is floored at zero so that a very high-generation plan reports 0 rather than a negative index. As §2.6 insists, the rounding in this last step is the *only* rounding in the whole chain; every intermediate quantity above is carried at full exact-decimal precision.

The **projected variant** feeds the plan's paper numbers into that routine: the airtightness figure is `design_ach50` and the duct leakage figure is `design_duct_leakage_cfm25_per_100sqft`. It runs when a plan model is registered, writing the plan's own `projected_index`, and again when a rating is opened on a home, copying the number onto the rating. The **confirmed variant** is described in §3.4.

### 3.2. Lots, Rating Files, and the Pinned Plan Snapshot

A builder representative registers each lot it intends to have rated as a `Home`, supplying the `subdivision_id`, the `plan_model_id` of the plan being built on that lot, a `lot_number` unique within the subdivision, and a `permit_date` as a `YYYY-MM-DD` calendar date. A repeated lot number in the same subdivision is `ERR_DUPLICATE_LOT_NUMBER`. The named plan model must belong to the *same* subdivision as the home and must still be `ACTIVE`; a plan from a different subdivision, or one that has been archived, is rejected with `ERR_PLAN_MODEL_MISMATCH`. A freshly registered lot has `sampling_role` of `UNASSIGNED`, a null `sample_set_id`, and `individual_testing_required` set to `false`, and its registration raises the owning subdivision's `homes_count` and `unsampled_home_count` each by one. Homes can be read individually and listed with optional filters on `subdivision_id`, `plan_model_id`, `sample_set_id` and `sampling_role`.

The `sampling_role` field tracks a home's part in the sampling protocol across four values: `UNASSIGNED` before it joins any set, `MEMBER` once it has been added to one, `TESTED` once the selector has picked it as the set's fully tested home, and `REPRESENTED` once the set has been closed and this home inherits the tested home's outcome. `individual_testing_required` is a one-way flag: once a sample set covering a home fails or is voided, that home may never be represented again and must be tested on its own merits.

Opening a **rating file** is the act of a certified rater and requires only a `home_id`, the `rater_id` of the rater of record, and — where the new file replaces a dead one — an optional `supersedes_rating_id`. Two things are captured at that instant and never recomputed. The home's current plan is pinned onto the rating as its own `plan_model_id`, so that any later edit to the builder's plan catalogue cannot move this rating's numbers; and the pinned plan's projected index is copied onto the rating as its `projected_index`. The pinned plan must satisfy the same subdivision-coherence and `ACTIVE`-status requirement as at lot registration, again under `ERR_PLAN_MODEL_MISMATCH`. A new rating starts with `stage` of `PROJECTED`, `compliance_status` of `UNDETERMINED`, `qa_status` of `NOT_SELECTED`, `registry_status` of `NOT_SUBMITTED`, and `file_locked` of `false`; `confirmed_index`, `confirmed_ach50`, `confirmed_duct_leakage_cfm25_per_100sqft`, `eri_target`, `submitted_index`, `registry_confirmation_number`, `rejection_reason` and `confirmed_at` are all null, and `compliance_path` is `NONE`.

A home may carry only one live rating. If the home already has a rating whose `stage` is any of `PROJECTED`, `ROUGH_IN_VERIFIED`, `CONFIRMED` or `REGISTERED`, a second rating is refused with `ERR_DUPLICATE_ACTIVE_RATING` — unless the request's `supersedes_rating_id` names that very rating *and* that rating has either reached `stage` `VOID` or been failed with `qa_status` of `QA_FAILED`. This is the only legitimate way to re-rate a home: the dead file is named explicitly, and the new file records the link. Ratings can be read individually and listed with optional filters on `home_id`, `rater_id`, `plan_model_id`, `supersedes_rating_id` and `stage`.

**Four independent dimensions.** A rating file is not a single state machine. It carries four dimensions simultaneously and they advance independently of one another. `stage` is the field-verification workflow: `PROJECTED`, then `ROUGH_IN_VERIFIED`, then `CONFIRMED`, then `REGISTERED`, with `VOID` as the one terminal value; note that `REGISTERED` is *not* terminal, because a registered rating can still be voided. `compliance_status` is the code dimension: `UNDETERMINED` until confirmation, then `PASSING` or `FAILING`, with `REMEDIATION_PENDING` marking the window in which a corrective action has been accepted but the file has not yet been re-confirmed. `qa_status` is the quality-assurance dimension: `NOT_SELECTED`, `QA_SELECTED`, `QA_PASSED`, or the terminal `QA_FAILED`. `registry_status` is the registry dimension: `NOT_SUBMITTED`, `PENDING`, `ACCEPTED` or `REJECTED`. Reading a rating returns all four dimensions and both indices.

### 3.3. Rough-In and Final Checkpoints

Field verification happens at up to two **checkpoints** per rating. Scheduling one is open to a rating field inspector or to a rater and requires the `rating_id`, the `inspector_id` of the person who will be on site, the `checkpoint` — `ROUGH_IN` for the pre-drywall visit or `FINAL` for the as-built visit — and the site window as `scheduled_start_utc` and `scheduled_end_utc`. The window start is inclusive and the window end is exclusive, and the end must fall strictly after the start. An optional `air_handler_installed` boolean, defaulting to `false`, records whether the air handler was already in place when the visit happened; as §2.7 notes, that fact relaxes the rough-in duct-leakage limit from 3.0 to 4.0. A newly scheduled checkpoint has `status` of `SCHEDULED` and `failed_test_count` of zero.

Inspectors cannot be in two places at once, and the rule allows for drive time. Each scheduled checkpoint's half-open window is expanded by a travel buffer of three quarters of an hour — 45 minutes — on *both* ends, and a new request is refused with `ERR_INSPECTOR_WINDOW_CONFLICT` if the resulting buffered interval overlaps the buffered interval of any other checkpoint that inspector already holds in `SCHEDULED` status. Because the intervals are half-open, two buffered windows that merely touch at an instant do not overlap and both bookings stand. Only `SCHEDULED` checkpoints participate: a checkpoint already closed as `PASSED` or `FAILED` no longer blocks anything. Checkpoints can be read individually and listed with filters on `rating_id`, `inspector_id` and `checkpoint`.

**Recording a measurement.** The assigned inspector records diagnostic tests against the checkpoint, supplying a `test_type` and a `measured_value`. `BLOWER_DOOR` measurements are raw CFM50 instrument readings; `DUCT_LEAKAGE_TOTAL` measurements are raw total-duct-leakage CFM25 readings. Each recorded test is append-only evidence and is stamped with `performed_at_utc` from the logical clock. It also carries its own `inspection_id`, and the list of a checkpoint's measurements is available for audit.

Recording a blower-door reading converts it to air changes per hour: multiply the `measured_value` by 60 minutes per hour, divide by the pinned plan's `conditioned_volume_cuft`, and round the quotient half-up to two decimal places to obtain `normalized_value`. Its `threshold_value` is the maximum permitted air changes per hour at 50 pascals for the subdivision's code edition and climate zone, from the table in §2.7.

Recording a duct-leakage reading normalizes it per unit floor area: multiply the `measured_value` by 100, divide by the pinned plan's `conditioned_floor_area_sqft`, and round the quotient half-up to two decimal places to obtain `normalized_value`. Its `threshold_value` depends on where the reading was taken. At a `FINAL` checkpoint the limit is 4.0. At a `ROUGH_IN` checkpoint the limit is 4.0 when `air_handler_installed` is true and 3.0 when it is false.

In both cases the graded outcome follows one rule: `result` is `PASS` when the rounded `normalized_value` is less than or equal to `threshold_value`, and `FAIL` otherwise. The comparison is inclusive and it is performed on the already-rounded two-decimal value, so a reading that normalizes to exactly the limit passes. A `FAIL` result increments the checkpoint's `failed_test_count`.

**Closing a checkpoint.** The assigned inspector closes the checkpoint once the measurements are in. Closure requires that the checkpoint still be `SCHEDULED`, and that the checkpoint's mandatory tests actually exist: a `ROUGH_IN` checkpoint needs at least one `DUCT_LEAKAGE_TOTAL` measurement, and a `FINAL` checkpoint needs one `BLOWER_DOOR` measurement and one `DUCT_LEAKAGE_TOTAL` measurement. A closure attempted without them is refused with `ERR_MISSING_GOVERNING_TEST`. Given the required tests, closure branches on the failure counter alone: when `failed_test_count` is zero the checkpoint becomes `PASSED`, and when it is one or more the checkpoint becomes `FAILED`. Closing an already-closed checkpoint is `ERR_INVALID_STATE`.

The two branches differ in exactly one respect and it matters. A `ROUGH_IN` checkpoint that closes as `PASSED` advances the rating's `stage` from `PROJECTED` to `ROUGH_IN_VERIFIED`. A `ROUGH_IN` checkpoint that closes as `FAILED` leaves the rating's `stage` exactly where it was — a failed rough-in never verifies, and the rating remains `PROJECTED`. A `FINAL` checkpoint's closure does not move `stage` in either branch; the as-built confirmation described next is a separate, rater-driven act. Crucially, a `FINAL` checkpoint that closed as `FAILED` still supplies perfectly usable governing measurements, so confirmation may and will proceed on it — and will land the rating in `FAILING` compliance rather than blocking. Skipping the rough-in checkpoint altogether is legal: only the final checkpoint governs confirmation.

### 3.4. Confirming the As-Built Rating and Selecting a Compliance Path

Confirmation is the pivot of the whole system and belongs to the rating's own rater of record. It is admissible from `stage` `PROJECTED` and from `stage` `ROUGH_IN_VERIFIED`, and the two entry points behave identically — the same preconditions, the same computations, the same downstream effects. In both cases the rating must not be file-locked, the rater of record must stand at `effective_certification_status` of `ACTIVE` or `PROBATION`, and there must exist a `FINAL` checkpoint on this rating whose `status` is `PASSED` or `FAILED` and which carries exactly one `BLOWER_DOOR` and one `DUCT_LEAKAGE_TOTAL` measurement. Without such a checkpoint the request fails with `ERR_MISSING_GOVERNING_TEST`.

Confirmation then does eight things, in this order. It copies the governing final blower-door measurement's `normalized_value` into the rating's `confirmed_ach50` and the governing final duct-leakage measurement's `normalized_value` into `confirmed_duct_leakage_cfm25_per_100sqft`. It re-runs the HERS index routine of §3.1 in its **confirmed variant** — identical arithmetic, but with the measured, normalized `confirmed_ach50` standing in for the plan's `design_ach50` and the measured `confirmed_duct_leakage_cfm25_per_100sqft` standing in for the plan's `design_duct_leakage_cfm25_per_100sqft` — and writes the result into `confirmed_index`. It snapshots the applicable ERI target from §2.7 into `eri_target`. It runs the compliance-path selection described below, which writes `compliance_path` and moves `compliance_status` from `UNDETERMINED` to either `PASSING` or `FAILING`. It stamps `confirmed_at` from the logical clock and sets `stage` to `CONFIRMED`. It increases the rater of record's `confirmed_rating_count` by one and then re-derives that rater's quality-assurance quota, described in §3.6, which may set `qa_files_owed` and `registry_hold`. If the selection landed on `FAILING`, it opens a corrective action against this rating with `reason` of `THRESHOLD_FAILURE` and `status` of `OPEN`, which raises the owning builder's `open_corrective_action_count` and thereby recomputes that builder's `sampling_eligible` to false. And if the rated home's `sampling_role` is `TESTED`, it advances the owning sample set's `status` from `SELECTED` to `TESTED`.

Because the same home routinely lands on a different index as built than it did on paper, the confirmed and projected numbers coexist on the rating permanently and neither overwrites the other.

**Selecting the compliance path.** Selection runs immediately after `confirmed_index` is written and reads nothing beyond the rating being confirmed, its pinned plan model, and its subdivision's `code_edition`, `climate_zone` and `compliance_path_preference`. Three facts are prepared first: whether the airtightness test passes, meaning `confirmed_ach50` is less than or equal to the maximum permitted air changes per hour for this edition and zone; whether the duct test passes, meaning `confirmed_duct_leakage_cfm25_per_100sqft` is less than or equal to 4.0; and the ERI target for this edition and zone. All comparisons are inclusive. Index comparisons are integer comparisons; airtightness and duct comparisons use the two-decimal normalized values.

Selection then proceeds as a waterfall whose first step is a hard branch, not a fall-through:

- **Step 0 — the binding election.** If the subdivision's `compliance_path_preference` is `PRESCRIPTIVE_PATH`, only the prescriptive path is available and the waterfall never continues past this step. The rating passes on the prescriptive path — `compliance_path` becomes `PRESCRIPTIVE` and `compliance_status` becomes `PASSING` — when the airtightness test passes, the duct test passes, and the pinned plan's `envelope_ua_btu_per_hr_f` is less than or equal to 0.12 multiplied by its `conditioned_floor_area_sqft`. Otherwise, and regardless of how good the index is, `compliance_path` becomes `NONE` and `compliance_status` becomes `FAILING`. A prescriptive-election subdivision therefore never records `ERI` or `PERFORMANCE` on any rating.
- **Step 1 — the ERI path**, reached only when `compliance_path_preference` is `ERI_PATH`. If `confirmed_index` is less than or equal to the ERI target, and the airtightness test passes, and the duct test passes, then `compliance_path` becomes `ERI` and `compliance_status` becomes `PASSING`.
- **Step 2 — the total-UA performance path.** If step 1 did not qualify, the home gets a second chance with a looser index allowance and a tighter envelope gate: if `confirmed_index` is less than or equal to the ERI target plus a tolerance of 5 index points, and the airtightness test passes, and the duct test passes, and the pinned plan's `envelope_ua_btu_per_hr_f` is less than or equal to 0.14 multiplied by its `conditioned_floor_area_sqft`, then `compliance_path` becomes `PERFORMANCE` and `compliance_status` becomes `PASSING`.
- **Step 3 — nothing qualifies.** `compliance_path` becomes `NONE` and `compliance_status` becomes `FAILING`, and the threshold-failure corrective action described above is opened.

Note that a failing airtightness or duct measurement is fatal on every one of the three paths: no amount of index headroom or envelope quality compensates for it.

**Re-confirmation after remediation.** A confirmed rating that has failed compliance is not stuck. Once the builder's remediation has been accepted — §3.7 — the rating's `compliance_status` sits at `REMEDIATION_PENDING`, and from there the rater of record may confirm the file again. This re-confirmation is a self-loop on `stage`: the rating is already `CONFIRMED` and stays `CONFIRMED`. It is admissible only when `compliance_status` is exactly `REMEDIATION_PENDING`, the file is not locked, and a `FINAL` checkpoint *newer* than the rating's current `confirmed_at` carries both governing measurements; confirming a `CONFIRMED` rating whose `compliance_status` is anything other than `REMEDIATION_PENDING` is `ERR_INVALID_STATE`. Re-confirmation re-evaluates the confirmed index and the compliance-path selection from the newest governing final measurements, rewrites `compliance_status` to `PASSING` or `FAILING` accordingly, writing `compliance_path` to the qualifying path or to `NONE`, and re-stamps `confirmed_at`. If the newest measurements still satisfy no path, a *further* `THRESHOLD_FAILURE` corrective action is opened and the cycle can repeat. The rater's `confirmed_rating_count` is **not** incremented a second time for the same rating, however many times it is re-confirmed.

### 3.5. The Sampling Protocol for Production Subdivisions

Sampling is the efficiency mechanism that makes production-scale rating economical: a group of near-identical homes permitted in the same period is grouped into a **sample set**, one of them is fully tested, and the rest inherit that home's outcome. It is also the mechanism most open to abuse, which is why it is gated at four separate levels — the subdivision must have `sampling_enabled` true, the builder must be `sampling_eligible`, the set must be the right size, and the homes must be genuinely comparable in permit date.

A certified rater opens a sample set against a `subdivision_id` with a `window_start_date` and a `window_end_date`, both `YYYY-MM-DD` dates, describing the closed interval of building-permit dates the set will cover; the end must be on or after the start. A subdivision with `sampling_enabled` false refuses the request with `ERR_SAMPLING_NOT_ENABLED`, and a builder that is not `sampling_eligible` — because it is `CUSTOM`, because its `status` is `SAMPLING_SUSPENDED`, or because it has open corrective actions — refuses it with `ERR_BUILDER_SAMPLING_INELIGIBLE`. A subdivision may run only one live sampling window at a time: if it already has a sample set in `FORMING`, `SELECTED` or `TESTED` status whose closed date interval intersects the requested one, the request is refused with `ERR_SAMPLE_WINDOW_CONFLICT`. Because both intervals are closed, two windows that share even a single endpoint date do intersect. Sets already closed as `CLOSED_PASS`, `FAILED_EXPANDED` or `VOIDED_SAMPLING` do not conflict with anything. A new set starts `FORMING` with `member_count`, `tested_member_count` and `represented_member_count` all zero, a null `tested_home_id` and a null `representative_index`. Sets can be read individually and listed with filters on `subdivision_id`, `tested_home_id` and `status`.

**Membership.** A certified rater adds a home to a forming set by supplying the `home_id` together with `expected_sample_set_version` as §2.9 requires. Four coherence checks apply. The home must belong to the same subdivision as the set, or the addition fails with `ERR_HOME_SUBDIVISION_MISMATCH`. The home must not already belong to some set — its `sample_set_id` must be null — or the addition fails with `ERR_HOME_ALREADY_SAMPLED`. The home's `permit_date` must lie inside the closed interval running from `window_start_date` through `window_end_date` inclusive, or the addition fails with `ERR_HOME_PERMIT_OUTSIDE_WINDOW`. And a home whose `individual_testing_required` flag is true may never be sampled again, so its addition fails with `ERR_REPRESENTED_HOME_NOT_TESTABLE`. A sample set may hold at most seven members; an addition that would push `member_count` above seven is refused with `ERR_SAMPLE_SET_SIZE_INVALID`. A successful addition writes the set's identifier into the home's `sample_set_id`, moves the home's `sampling_role` from `UNASSIGNED` to `MEMBER`, raises the set's `member_count`, and re-derives the subdivision's coverage ledger so that `sampled_home_count` rises by one and `unsampled_home_count` falls by one. The `data` of that `201` response is the updated `Home`, not the sample set, so a client that needs the set's new `version` or counters must read the set back.

Withdrawal is the exact compensating action. A certified rater withdraws a named member from a forming set, again supplying `expected_sample_set_version`. Withdrawal clears the home's `sample_set_id` back to null, returns its `sampling_role` to `UNASSIGNED`, lowers the set's `member_count`, and re-derives the coverage ledger so that `sampled_home_count` falls by one and `unsampled_home_count` rises by one. Its `200` response likewise carries the updated `Home` rather than the sample set, so the set's post-withdrawal `status`, `version` and counters are again observed only by reading the set back. Add-then-withdraw of the same home restores all three subdivision counters to exactly their pre-addition values, as §2.10 requires.

**Selecting the tested home.** Provider staff run the selector over the set's members. Selection requires the set to be `FORMING`, the subdivision to still have `sampling_enabled` true, the builder to still be `sampling_eligible`, and the membership to number at least two and at most seven — a set with fewer than two members cannot be selected and is refused with `ERR_SAMPLE_SET_SIZE_INVALID`.

The selector chooses the *worst-performing* member on paper, so that a passing sample set genuinely bounds the whole group. It first filters the set's own member homes down to candidates, keeping a member only when its `individual_testing_required` flag is false and when there exists a rating on that home whose `stage` is `PROJECTED` and whose `registry_status` is `NOT_SUBMITTED`. No home outside this set's membership is ever considered. If the candidate list comes out empty the whole selection is rejected with `ERR_NO_ELIGIBLE_SAMPLE_HOME` and nothing changes. Otherwise the candidates are ranked by their rating's `projected_index` in descending order — the highest, worst index first. Ties are broken in a fixed two-stage order: first by the `conditioned_floor_area_sqft` of the home's pinned plan model in descending order, largest first; and then, if still tied, by the home's `created_at` in ascending order, earliest first, compared at millisecond precision. The home's `id` is never used as a tie-breaker. The first candidate after that ranking becomes the tested home.

Selection then records the winner's identifier in the set's `tested_home_id`, moves that home's `sampling_role` from `MEMBER` to `TESTED`, sets `tested_member_count` to 1, and moves the set's `status` from `FORMING` to `SELECTED`. Selecting a set that is not `FORMING` is `ERR_INVALID_STATE`. From that point the tested home is rated and confirmed like any other home, and its confirmation — as §3.4 describes — advances the set from `SELECTED` to `TESTED` automatically, without any client request against the set.

**Closing the set.** Provider staff close a `TESTED` set, and the closure routes on the tested home's compliance outcome. Before routing, the closure must be routable at all: the set's `tested_home_id` must be populated and that home's rating must have reached `stage` `CONFIRMED` or `REGISTERED`. Attempting to close a set that is still merely `SELECTED` — that is, one whose tested home has not been confirmed and therefore has no confirmed index at all — always fails with `ERR_SAMPLE_SET_NO_TESTED_RATING`, because the aggregation below would have an empty input set. A tested rating that *is* confirmed but is `FAILING` passes this routability check and routes to the failure branch.

On the **passing** branch — the tested home's rating has `compliance_status` of `PASSING` — the representative index is computed in three strictly ordered steps that must not be interleaved. Step one collects the `confirmed_index` values of the set's member homes whose `sampling_role` is `TESTED` and whose rating is at `stage` `CONFIRMED` with `compliance_status` of `PASSING`; represented and unassigned member homes are excluded from this collection entirely. Step two reduces that collection to its maximum — the worst-performing tested home — and writes it into the set's `representative_index`; because exactly one home per set is ever `TESTED`, that maximum is in practice that single home's confirmed index, and there is no rounding since the inputs are already whole numbers. Step three assigns the outcome: every member home other than the tested home has its `sampling_role` set to `REPRESENTED`, the set's `represented_member_count` is set to `member_count` less one, and each represented home's rating — where one exists — has its `confirmed_index` set to the set's `representative_index` and its `compliance_status` set to `PASSING`. The values written in step three are never fed back into steps one or two: a represented home's projected index and its newly assigned confirmed index lie outside the input set of the maximum. The set's `status` becomes `CLOSED_PASS`.

On the **failing** branch — the tested home's rating has `compliance_status` of `FAILING` — the set's `status` becomes `FAILED_EXPANDED`, its `representative_index` stays null, and a five-hop cascade expands the group into individual testing. First, every member home other than the tested home has `individual_testing_required` set to `true` and its `sampling_role` set to `REPRESENTED`. Second, each of those homes' existing ratings has its `confirmed_index` cleared to null and its `compliance_status` set to `FAILING`, which for a rating that had been `PASSING` is a genuine regression of the compliance dimension and also resets its `compliance_path` to `NONE`. Third, each of those newly failing ratings receives a corrective action with `reason` of `SAMPLE_SET_FAILURE` and `status` of `OPEN`. Fourth, those creations raise the builder's `open_corrective_action_count` by one apiece. Fifth, the builder's `status` is set to `SAMPLING_SUSPENDED`, which recomputes its `sampling_eligible` to false. The practical consequence is severe and intended: one bad tested home costs the builder its entire sampling privilege plus a corrective action on every sibling in the set.

Closing a set that is not `TESTED` is otherwise `ERR_INVALID_STATE`, and the three closed statuses — `CLOSED_PASS`, `FAILED_EXPANDED` and `VOIDED_SAMPLING` — are all terminal.

### 3.6. Quality-Assurance Sampling, Rater Standing, and the Major-Failure Cascade

The provider's own accreditation rests on auditing a share of its raters' output, and the system enforces that share arithmetically rather than by policy memo. Each rater carries a quota derived from three inputs: `confirmed_rating_count`, which counts that rater's ratings at `stage` `CONFIRMED` or `REGISTERED`; `qa_completed_count`, which counts the quality-assurance reviews of that rater's files that have reached `COMPLETED` status; and `certification_status`, which selects the rate. A rater in good standing is sampled at one file in ten — a rate of 0.10 — while a rater on `PROBATION` is sampled at every file, a rate of 1.00. The quota is then: multiply the applicable rate by `confirmed_rating_count` in exact decimal arithmetic and take the floor of that product to get the number of files required; subtract `qa_completed_count` from it; and take the greater of that difference and zero to get `qa_files_owed`. `registry_hold` is true exactly when `qa_files_owed` is greater than zero. Concretely, a standard-rate rater with nine confirmed files owes nothing, and the tenth confirmation puts one file on the slate. The quota is re-derived every time any of its three inputs moves — on a rating confirmation, on a review completion, and on a reinstatement.

**Assigning a review.** Provider staff assign a review with the `rating_id`, the `reviewer_id` of the designee who will perform it, and a `review_type` of either `FILE_REVIEW`, which inspects the rating file as submitted, or `FIELD_REVIEW`, which re-inspects the home itself. Assignment requires the rating to be at `stage` `CONFIRMED` or `REGISTERED`, its `qa_status` to still be `NOT_SELECTED`, and the reviewer to be someone other than the rating's own rater. A successful assignment creates the review with `status` of `ASSIGNED`, a null `result` and a null `findings_note`, and moves the rating's `qa_status` from `NOT_SELECTED` to `QA_SELECTED`. Reviews can be read individually and listed with filters on `rating_id`, `reviewer_id` and `status`.

**Completing a review.** Only the assigned designee may record the outcome, supplying a `result` of `PASS`, `FAIL_MINOR` or `FAIL_MAJOR` together with a `findings_note` narrative. Completion requires the review still be `ASSIGNED`; a second completion is `ERR_INVALID_STATE`. In all three branches the review's `status` becomes `COMPLETED`, the supplied `result` and `findings_note` are recorded, the reviewee rater's `qa_completed_count` rises by one, and that rater's quota is re-derived afterwards. Beyond that shared core the three branches diverge sharply, and each is spelled out below in full because the differences are exactly where the file's fate is decided.

A **`PASS`** clears the file. The rating's `qa_status` moves from `QA_SELECTED` to `QA_PASSED`. The reviewee's `qa_failure_count` does not move and their `certification_status` does not move. No corrective action is opened, no package is touched, no sample set is voided, and the builder's counters do not move. With `qa_completed_count` up by one, the reviewee's `qa_files_owed` typically falls by one and `registry_hold` clears when it reaches zero.

A **`FAIL_MINOR`** is a finding, not a condemnation, and it deliberately does **not** move the quality-assurance dimension: the rating's `qa_status` stays `QA_SELECTED`, because only a major failure fails a file. Instead a corrective action with `reason` of `QA_FINDING` and `status` of `OPEN` is opened against the reviewed rating, which raises the builder's `open_corrective_action_count` by one and recomputes that builder's `sampling_eligible` to false. The reviewee's `qa_failure_count` rises by one and their `certification_status` steps one notch down the disciplinary ladder — from `ACTIVE` to `PROBATION`, or from `PROBATION` to `SUSPENDED` if they were already on probation. Because probation switches the sampling rate from 0.10 to 1.00, the quota is then re-derived at the full rate, so `qa_files_owed` becomes the greater of zero and `confirmed_rating_count` less `qa_completed_count`, with `registry_hold` following that value. Immediately after the review that caused the probation those two typically read zero and false, since the review just completed brought the counts level; the rater's very next confirmation raises `confirmed_rating_count` without raising `qa_completed_count`, and the hold bites at that point. No package is revoked and no sample set is voided on a minor failure. The file therefore remains submittable, once the `QA_FINDING` action has been accepted.

A **`FAIL_MAJOR`** condemns the file and triggers the system's widest cascade. The rating's `qa_status` becomes `QA_FAILED`, which is terminal for that dimension — the quality-assurance dimension never recovers, and the only route forward for that home is a fresh rating that supersedes this one. The reviewee's `qa_failure_count` rises by one and their `certification_status` steps toward `SUSPENDED` on the same ladder as a minor failure. Then five hops run, in order. Hop one: every documentation package of this rating whose `status` is `ISSUED` becomes `REVOKED` with `revocation_reason` of `QA_MAJOR_FAILURE`. Hop two: each such revocation lowers the builder's `certified_incentive_cents` by that package's `certified_amount_cents` and raises the builder's `revoked_package_count` by one. Hop three: once `revoked_package_count` stands at one or more, the builder's `status` is forced to `SAMPLING_SUSPENDED` and its `sampling_eligible` becomes false. Hop four: because the builder is no longer sampling-eligible, every sample set belonging to any of that builder's subdivisions whose `status` is `FORMING`, `SELECTED` or `TESTED` transitions to `VOIDED_SAMPLING`. Hop five: each voided set releases its members — every member home has its `sample_set_id` cleared to null, its `sampling_role` returned to `UNASSIGNED`, and its `individual_testing_required` set to `true` — the voided set's `tested_home_id` and `representative_index` are cleared to null and its `member_count`, `tested_member_count` and `represented_member_count` are all set to zero, the affected subdivision's `sampled_home_count` falls and its `unsampled_home_count` rises by the same number of homes so that the coverage ledger stays balanced, and every plan model of that subdivision has its `status` set to `ARCHIVED`. An archived plan model can no longer back a new lot or a new rating, per §3.2.

**Rater standing over time.** A rater's disciplinary state is a cycle, not a ratchet. A first qualifying failure — minor or major — takes `certification_status` from `ACTIVE` to `PROBATION`; a second takes it from `PROBATION` to `SUSPENDED`, at which point that person may open no ratings, perform no confirmations, run no inspections and submit no files. Provider staff may reinstate a rater from either `PROBATION` or `SUSPENDED` after remedial training, supplying the `training_completed_at` instant and an optional `note`. Reinstatement sets `certification_status` back to `ACTIVE`, resets `qa_failure_count` to zero, and re-derives the quota at the standard 0.10 rate, which normally clears `qa_files_owed` and `registry_hold`. Reinstating a rater who is already `ACTIVE` is `ERR_INVALID_STATE`. Reinstatement never touches `cert_expires_at`, so a rater whose certificate has lapsed remains `EXPIRED` in `effective_certification_status` and remains blocked no matter how many times they are reinstated — the fix for expiry is a new certificate, not a reinstatement.

### 3.7. Builder Corrective Action

Corrective actions are never created by a client request. Every one of them is opened by a cascade: a failing confirmation opens a `THRESHOLD_FAILURE` action, a sample-set failure opens a `SAMPLE_SET_FAILURE` action on each affected sibling, and a minor quality-assurance finding opens a `QA_FINDING` action. All three arrive with `status` of `OPEN`, an `attempt_count` of zero and a null `remediation_note`, and all three can be listed against the rating they were opened on.

The builder representative responds by submitting a remediation. Submission requires the action to be `OPEN` — or `REJECTED`, which is how a re-submission works — requires the rating not to be voided, and requires the acting representative's `X-User-ID` to resolve to the builder that owns the rating's subdivision. Each submission sets the action's `status` to `SUBMITTED`, raises its `attempt_count` by one, and records the supplied `remediation_note`, overwriting whatever narrative the previous attempt had left.

Provider staff then adjudicate a `SUBMITTED` action with a `decision` of `ACCEPT` or `REJECT` and an optional `note`; adjudicating an action in any other status is `ERR_INVALID_STATE`. An `ACCEPT` sets `status` to `ACCEPTED`, lowers the builder's `open_corrective_action_count` by one and recomputes the builder's `sampling_eligible` accordingly, and — where the rating's `compliance_status` was `FAILING` — moves that rating to `REMEDIATION_PENDING`, which is precisely the state that unlocks the re-confirmation self-loop of §3.4. `ACCEPTED` is terminal.

A `REJECT` behaves in one of two ways depending on how many attempts the builder has already made. When `attempt_count` is less than three, the action's `status` becomes `REJECTED` and the builder may submit again, giving the cycle submitted → rejected → submitted. A rejected action is still unresolved for the purposes of registry submission and package issuance even though it is no longer carried in the builder's `open_corrective_action_count`. When the rejection lands on the third attempt — `attempt_count` standing at exactly three — the action does not loop again: its `status` becomes `ESCALATED`, which is terminal, it continues to be counted as open so the builder stays sampling-ineligible, and the builder's `status` is set to `SAMPLING_SUSPENDED`.

### 3.8. Registry Submission, File Locking, and Voiding

Submitting a rating file to the national registry is the rater of record's act, and it is the moment the file stops being editable. Submission is admissible when the rating's `stage` is `CONFIRMED`, its `compliance_status` is `PASSING`, its `registry_status` is either `NOT_SUBMITTED` or `REJECTED`, its `file_locked` flag is false, the rater of record stands at `effective_certification_status` of `ACTIVE` or `PROBATION`, and that rater's `registry_hold` is false. A rating whose `compliance_status` is not `PASSING`, or whose `qa_status` is `QA_FAILED`, is refused with `ERR_RATING_NOT_COMPLIANT`. A rating carrying a corrective action in `OPEN`, `SUBMITTED`, `REJECTED` or `ESCALATED` status is refused with `ERR_OPEN_CORRECTIVE_ACTION` — note that this list includes `REJECTED`, so a builder mid-appeal blocks submission. A rater carrying a quality-assurance deficit, meaning `registry_hold` is true because `qa_files_owed` is above zero, is refused with `ERR_RATER_QA_DEFICIT`. A successful submission moves `registry_status` from `NOT_SUBMITTED` to `PENDING`, freezes the current `confirmed_index` into `submitted_index` so that the number the registry saw is preserved independently of any later recomputation, and sets `file_locked` to true.

From that point the lock blocks any further field work on the file: scheduling a checkpoint, recording a measurement, closing a checkpoint, confirming and re-submitting are all refused with `ERR_RATING_FILE_LOCKED`. As §2.8 records, the lock deliberately does **not** block documentation-package work.

Provider staff record the registry's answer with an `outcome` of `ACCEPT` or `REJECT`. This is only admissible while `registry_status` is `PENDING`. An `ACCEPT` requires a `confirmation_number` in the payload; it sets `registry_status` to `ACCEPTED`, records the supplied number in `registry_confirmation_number`, advances the rating's `stage` from `CONFIRMED` to `REGISTERED`, and leaves `file_locked` true. A `REJECT` requires a `rejection_reason` in the payload; it sets `registry_status` to `REJECTED`, records the supplied text in `rejection_reason`, clears `submitted_index` back to null, and — importantly — sets `file_locked` back to false so that the file re-opens for correction. From `REJECTED` the rater may submit again, at which point `rejection_reason` is cleared to null, `registry_status` returns to `PENDING` and the file locks once more, giving the cycle pending → rejected → pending.

**Voiding.** Provider staff may void a rating at any `stage` other than `VOID` itself, supplying a `reason`; a registered rating is emphatically not immune. Voiding sets `stage` to `VOID`, forces `compliance_status` to `FAILING`, and sets `file_locked` to true, and it runs a three-hop cascade over the money side of the file. Hop one: every documentation package of this rating whose `status` is `ISSUED` becomes `REVOKED` with `revocation_reason` of `RATING_VOID`. Hop two: each such revocation lowers the builder's `certified_incentive_cents` by that package's `certified_amount_cents` and raises the builder's `revoked_package_count` by one. Hop three: once `revoked_package_count` stands at one or more, the builder's `status` becomes `SAMPLING_SUSPENDED` and its `sampling_eligible` recomputes to false. Separately, every documentation package of this rating still sitting at `DRAFT` becomes `SUPERSEDED`. `VOID` is terminal for the stage dimension, and a voided rating blocks scheduling, testing, checkpoint closure, confirmation, registry submission, review assignment, remediation submission, package drafting and package issuance, all with `ERR_RATING_VOID`.

### 3.9. Tax-Credit and Utility-Program Documentation Packages

The commercial output of a rating is a documentation package: either a `TAX_CREDIT_45L` package supporting a federal tax credit claim, or a `UTILITY_PROGRAM` package supporting a utility incentive claim. The builder representative drafts one against a `rating_id` with a `package_type` and the `expected_rating_version` guard of §2.9. A draft is created with `status` of `DRAFT`, a null `certified_amount_cents`, a null `revocation_reason` and a null `issued_at`; any earlier package of the *same* `package_type` on the *same* rating that is still at `DRAFT` becomes `SUPERSEDED`, and the drafting itself raises the rating's `version` by one. `SUPERSEDED` is terminal and involves no ledger movement, because a draft has never contributed to the builder's money ledger. Drafts and issued packages alike can be listed against their rating.

Drafting computes the **provisional** amount into `provisional_amount_cents`, and issuance recomputes the very same routine in its **certified** variant into `certified_amount_cents`. The two variants read different inputs and that is the entire point: the provisional figure uses the rating's `projected_index` together with the pinned plan's `design_ach50` and `design_duct_leakage_cfm25_per_100sqft`, all paper values available before anyone has been on site, while the certified figure uses the rating's `confirmed_index` together with the measured `confirmed_ach50` and `confirmed_duct_leakage_cfm25_per_100sqft`. The two can differ in tier selection and in every per-measure credit, and the gap between `provisional_amount_cents` and `certified_amount_cents` is exactly what the builder gains or loses by building better or worse than it drew. Only the certified figure ever moves `certified_incentive_cents`. Both variants read one rating, its pinned plan model and the package's own `package_type`; there is no aggregation across packages.

For a **`TAX_CREDIT_45L`** package the amount is a flat tier chosen on the index alone, and `line_items` is an empty array. An index of 45 or lower earns 250,000 cents — two thousand five hundred dollars. An index above 45 but no higher than 55 earns 100,000 cents, one thousand dollars. An index above 55 earns nothing at all: the amount is 0 cents.

For a **`UTILITY_PROGRAM`** package the amount is the sum of four per-measure line items, computed in a pinned rounding order that must not be rearranged: **each line item is rounded to whole cents first, the rounded line items are then summed, and the cap is applied last.** Never sum first and round afterwards. The four items are, in this fixed order:

- `ENVELOPE` — 37.5 cents for every square foot of the pinned plan's `conditioned_floor_area_sqft`.
- `DUCTS` — 1,250 cents for each unit by which the duct leakage figure undershoots the 4.0 final limit, where the undershoot is the greater of zero and 4.0 less the applicable duct leakage figure, so a home at or above the limit earns nothing on this line.
- `AIR` — 1,500 cents for each air change per hour by which the airtightness figure undershoots a baseline of 5.0, again taken as the greater of zero and 5.0 less the applicable airtightness figure.
- `INDEX` — 2,250 cents for each index point by which the index undershoots a baseline of 60, again taken as the greater of zero and 60 less the applicable index.

Each of those four products is rounded half-up to whole cents on its own, and each is recorded as a `line_items` entry carrying a `code` — `ENVELOPE`, `DUCTS`, `AIR`, `INDEX` — and an `amount_cents`, in that order. The four rounded amounts are then added together, and the package amount is the smaller of that subtotal and a per-package cap of 150,000 cents — one thousand five hundred dollars. The `line_items` array records the uncapped per-measure amounts even when the cap bites.

**Issuance.** Provider staff certify and issue a `DRAFT` package, and this is the only operation in the system that adds money to a builder's ledger. Issuance requires the package to be `DRAFT`; the rating to be at `stage` `CONFIRMED` or `REGISTERED` with `compliance_status` of `PASSING` and `qa_status` other than `QA_FAILED`, failing which the request is refused with `ERR_RATING_NOT_COMPLIANT`; and no corrective action on that rating to be sitting in `OPEN`, `SUBMITTED`, `REJECTED` or `ESCALATED` status, failing which it is refused with `ERR_OPEN_CORRECTIVE_ACTION`. It further requires the rating to be efficient enough for the programme in question: a `TAX_CREDIT_45L` package needs a `confirmed_index` of 55 or lower and a `UTILITY_PROGRAM` package needs a `confirmed_index` of 50 or lower, and an index above the applicable ceiling is refused with `ERR_PACKAGE_NOT_ELIGIBLE`. Note the asymmetry with the tier table above: a home with a confirmed index of 58 is not merely worth zero cents on the tax-credit tier, it cannot be issued at all.

For a `UTILITY_PROGRAM` package one further gate applies. The builder's `utility_program_budget_cents` is a hard ceiling on how much utility-programme money may be certified against it at once: if the builder's current `certified_incentive_cents` plus this package's newly computed certified amount would exceed `utility_program_budget_cents`, the issuance is refused with `ERR_PROGRAM_BUDGET_EXCEEDED`. Equality is permitted — a package that lands the ledger exactly on the budget is issued. This gate does not apply to tax-credit packages.

A successful issuance recomputes the certified variant into `certified_amount_cents` and rewrites `line_items` from the measured values, sets `status` to `ISSUED`, stamps `issued_at` from the logical clock, and raises the builder's `certified_incentive_cents` by the certified amount. Issuing a package that is not `DRAFT` is `ERR_INVALID_STATE`. The revocation paths of §3.6 and §3.8 are the compensating counterparts: after an issue-then-revoke pair the builder's `certified_incentive_cents` reads exactly what it read before the issue, and the package's `revocation_reason` records which of the two cascades — `QA_MAJOR_FAILURE` or `RATING_VOID` — took the money back. `REVOKED` is terminal, and a revoked package can never be re-issued.

## 4. Endpoint Definitions

Operations that bring a new, independently addressable resource into existence — registering a builder, a subdivision, a plan model, a lot, a certified person, a rating file, a checkpoint, a diagnostic measurement, a sample set, a quality-assurance review or a documentation package draft, and adding a home to a sample set — return `201 Created`. Every other mutating operation modifies a resource that already exists and returns `200 OK`. All read operations return `200 OK`. The API is mounted at the server root; there is no common path prefix.

The table below is a routing summary only. It deliberately does not restate request bodies, response bodies or side effects: those live in the §3 narratives, and a complete implementation of any row requires reading the corresponding workflow section.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| POST | `/builders` | Register a builder client of the rating provider | RatingProviderAdmin |
| GET | `/builders/{id}` | Read a builder with its live sampling eligibility and money ledger | RatingProviderAdmin, CertifiedRater, QADesignee, BuilderRep |
| POST | `/subdivisions` | Open a subdivision under a builder, fixing its code edition, climate zone and compliance-path election | RatingProviderAdmin |
| GET | `/subdivisions/{id}` | Read a subdivision with its home-coverage ledger | RatingProviderAdmin, CertifiedRater, FieldInspector, QADesignee, BuilderRep |
| GET | `/subdivisions` | List subdivisions, optionally filtered by builder | RatingProviderAdmin, CertifiedRater, QADesignee, BuilderRep |
| POST | `/plan-models` | Register a plan model and compute its plan-based projected HERS index | CertifiedRater |
| GET | `/subdivisions/{id}/plan-models` | List the plan models offered in a subdivision | RatingProviderAdmin, CertifiedRater, FieldInspector, QADesignee, BuilderRep |
| POST | `/homes` | Register a lot in a subdivision against one of its plan models | BuilderRep |
| GET | `/homes/{id}` | Read a home with its sampling role | RatingProviderAdmin, CertifiedRater, FieldInspector, QADesignee, BuilderRep |
| GET | `/homes` | List homes filtered by subdivision, plan model, sample-set membership or sampling role | RatingProviderAdmin, CertifiedRater, FieldInspector, QADesignee, BuilderRep |
| POST | `/raters` | Certify a rater, rating field inspector or QA designee | RatingProviderAdmin |
| GET | `/raters/{id}` | Read a rater with effective certification status and QA quota | RatingProviderAdmin, CertifiedRater, FieldInspector, QADesignee |
| POST | `/raters/{id}/reinstate` | Reinstate a rater from probation or suspension after remedial training | RatingProviderAdmin |
| POST | `/ratings` | Open a rating on a home; pins the home's plan model and copies its projected index | CertifiedRater |
| GET | `/ratings/{id}` | Read a rating with all four state dimensions and its indices | RatingProviderAdmin, CertifiedRater, FieldInspector, QADesignee, BuilderRep |
| GET | `/ratings` | List ratings filtered by home, rater, pinned plan model, superseded predecessor or stage | RatingProviderAdmin, CertifiedRater, FieldInspector, QADesignee, BuilderRep |
| POST | `/ratings/{id}/confirm` | Confirm the as-built rating from the governing final checkpoint measurements | CertifiedRater |
| POST | `/ratings/{id}/void` | Void a rating; revokes its issued packages and unwinds the builder ledger | RatingProviderAdmin |
| POST | `/ratings/{id}/submit-to-registry` | Submit the rating file to the registry and lock it | CertifiedRater |
| POST | `/ratings/{id}/registry-decision` | Record the registry's accept or reject decision | RatingProviderAdmin |
| POST | `/inspections` | Schedule a rough-in or final checkpoint for an inspector, honouring the travel-buffered window rule | FieldInspector, CertifiedRater |
| GET | `/inspections/{id}` | Read an inspection with its failed-test counter | RatingProviderAdmin, CertifiedRater, FieldInspector, QADesignee, BuilderRep |
| GET | `/inspections` | List inspections filtered by rating, inspector or checkpoint | RatingProviderAdmin, CertifiedRater, FieldInspector, QADesignee, BuilderRep |
| POST | `/inspections/{id}/tests` | Record a blower-door or duct-leakage measurement; normalizes and grades it | FieldInspector |
| GET | `/inspections/{id}/tests` | List the append-only diagnostic measurements of a checkpoint | RatingProviderAdmin, CertifiedRater, FieldInspector, QADesignee, BuilderRep |
| POST | `/inspections/{id}/complete` | Close a checkpoint as passed or failed based on its recorded tests | FieldInspector |
| POST | `/sample-sets` | Open a sampling window for a production subdivision | CertifiedRater |
| GET | `/sample-sets/{id}` | Read a sample set with its membership counters, tested home and representative index | RatingProviderAdmin, CertifiedRater, FieldInspector, QADesignee, BuilderRep |
| GET | `/sample-sets` | List sample sets filtered by subdivision, tested home or status | RatingProviderAdmin, CertifiedRater, QADesignee, BuilderRep |
| POST | `/sample-sets/{id}/homes` | Add a home to a forming sample set, guarded by the set's version | CertifiedRater |
| POST | `/sample-sets/{id}/homes/{home_id}/withdraw` | Withdraw a home from a forming sample set, guarded by the set's version | CertifiedRater |
| POST | `/sample-sets/{id}/select` | Run the tested-home selector over the set's members | RatingProviderAdmin |
| POST | `/sample-sets/{id}/close` | Close the set: propagate the representative index, or fail it and expand to individual testing | RatingProviderAdmin |
| POST | `/qa-reviews` | Assign a QA file or field review to a designee other than the rating's rater | RatingProviderAdmin |
| GET | `/qa-reviews/{id}` | Read a QA review with its result and findings | RatingProviderAdmin, CertifiedRater, QADesignee |
| GET | `/qa-reviews` | List QA reviews filtered by rating, reviewer or status | RatingProviderAdmin, CertifiedRater, QADesignee |
| POST | `/qa-reviews/{id}/complete` | Record the QA outcome; a major failure cascades across packages, ledger and sampling | QADesignee |
| GET | `/ratings/{id}/corrective-actions` | List the corrective actions opened against a rating | RatingProviderAdmin, CertifiedRater, QADesignee, BuilderRep |
| POST | `/corrective-actions/{id}/submit` | Builder submits or re-submits a remediation response | BuilderRep |
| POST | `/corrective-actions/{id}/review` | Provider accepts or rejects the remediation; the third rejection escalates | RatingProviderAdmin |
| POST | `/document-packages` | Draft a tax-credit or utility-program package against a rating, guarded by the rating's version | BuilderRep |
| POST | `/document-packages/{id}/issue` | Certify and issue a drafted package, moving the builder's money ledger | RatingProviderAdmin |
| GET | `/ratings/{id}/document-packages` | List the documentation packages of a rating | RatingProviderAdmin, CertifiedRater, QADesignee, BuilderRep |
| POST | `/_clock/set_current_utc` | Test-driving capability: set the server's logical clock and re-derive every rater's effective certification status | RatingProviderAdmin |

## 5. Error Code Catalogue

Trigger conditions for every code below are stated in the §2 and §3 narratives; the relative order in which competing conditions are evaluated is fixed by §2.8.

| Error ID | HTTP Status Code |
| --- | --- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN_ROLE` | 403 |
| `ERR_NOT_RESOURCE_OWNER` | 403 |
| `ERR_INVALID_REQUEST` | 422 |
| `ERR_BUILDER_NOT_FOUND` | 404 |
| `ERR_SUBDIVISION_NOT_FOUND` | 404 |
| `ERR_PLAN_MODEL_NOT_FOUND` | 404 |
| `ERR_HOME_NOT_FOUND` | 404 |
| `ERR_RATER_NOT_FOUND` | 404 |
| `ERR_RATING_NOT_FOUND` | 404 |
| `ERR_INSPECTION_NOT_FOUND` | 404 |
| `ERR_SAMPLE_SET_NOT_FOUND` | 404 |
| `ERR_QA_REVIEW_NOT_FOUND` | 404 |
| `ERR_CORRECTIVE_ACTION_NOT_FOUND` | 404 |
| `ERR_DOCUMENT_PACKAGE_NOT_FOUND` | 404 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_RATING_VOID` | 409 |
| `ERR_RATING_FILE_LOCKED` | 409 |
| `ERR_STALE_RATING_VERSION` | 412 |
| `ERR_STALE_SAMPLE_SET_VERSION` | 412 |
| `ERR_CERTIFICATION_INVALID` | 422 |
| `ERR_CERT_LEVEL_INSUFFICIENT` | 422 |
| `ERR_SEGREGATION_OF_DUTIES` | 422 |
| `ERR_MISSING_GOVERNING_TEST` | 409 |
| `ERR_REPRESENTED_HOME_NOT_TESTABLE` | 422 |
| `ERR_PLAN_MODEL_MISMATCH` | 422 |
| `ERR_HOME_SUBDIVISION_MISMATCH` | 422 |
| `ERR_DUPLICATE_LOT_NUMBER` | 409 |
| `ERR_DUPLICATE_PLAN_CODE` | 409 |
| `ERR_DUPLICATE_ACTIVE_RATING` | 409 |
| `ERR_SAMPLING_NOT_ENABLED` | 422 |
| `ERR_HOME_ALREADY_SAMPLED` | 409 |
| `ERR_HOME_PERMIT_OUTSIDE_WINDOW` | 422 |
| `ERR_SAMPLE_SET_SIZE_INVALID` | 422 |
| `ERR_BUILDER_SAMPLING_INELIGIBLE` | 422 |
| `ERR_NO_ELIGIBLE_SAMPLE_HOME` | 422 |
| `ERR_SAMPLE_SET_NO_TESTED_RATING` | 409 |
| `ERR_RATING_NOT_COMPLIANT` | 422 |
| `ERR_OPEN_CORRECTIVE_ACTION` | 409 |
| `ERR_RATER_QA_DEFICIT` | 422 |
| `ERR_PACKAGE_NOT_ELIGIBLE` | 422 |
| `ERR_INSPECTOR_WINDOW_CONFLICT` | 409 |
| `ERR_SAMPLE_WINDOW_CONFLICT` | 409 |
| `ERR_PROGRAM_BUDGET_EXCEEDED` | 422 |
