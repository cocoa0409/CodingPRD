# Consumer Health Data Compliance API — Product Requirements Document

## 1. Introduction

Consumer health applications sit in an uncomfortable regulatory gap. A meditation tracker, a cycle app, or a symptom journal is usually not a HIPAA covered entity, yet the data it gathers — diagnoses volunteered in a free-text field, heart-rate traces from a wrist sensor, precise location that reveals a clinic visit, and above all the *inferences* the product draws from all three — is exactly the material that the newer consumer health data statutes were written to govern. Product teams therefore need to answer a sequence of hard questions in a defensible, auditable order: are we covered, by which regime, over which of our data elements, on what consent basis, disclosed in whose privacy policy, and with which downstream vendors bound to delete on command.

This document specifies the Consumer Health Data Compliance API, the internal system of record that a consumer health technology company uses to answer those questions once and keep the answers current. The API is mounted under `/health-data`. It holds the product's applicability analysis, its inventory of collected data elements and their consumer-health classification, its declared processing purposes and the element-to-purpose wiring, its three-axis consent architecture, its versioned privacy policy text with a content-completeness score, its consumer rights queue with verification and downstream deletion fan-out, its geofencing register for health facilities, its vendor and processor agreements with flow-down and audit clauses, its breach reportability analysis under both the health-specific and the general rules, and its documented security risk program.

Two design commitments run through the whole specification. First, **compliance posture is derived, never asserted**: a product's regulatory track, its regulated scope, its policy currency, and its security program standing are all computed from approved artefacts and recomputed whenever those artefacts move. Second, **every regulated action is gated on the posture it depends on**: an element-purpose mapping cannot go live under an undetermined applicability track or a lapsed privacy policy, a location campaign cannot run where the law forbids it, and a vendor cannot receive regulated data without an executed agreement carrying both a flow-down clause and audit rights. The consequence is a system with long cascades — terminating one vendor agreement can, in a single request, suspend mappings, unseat a published policy, lapse the product's policy state, and pause every running location campaign — and those cascades are specified exhaustively below.

## 2. Global Specifications & System-Wide Principles

This section defines the contracts that hold for every endpoint: authentication, envelope shape, pagination, identity, the logical clock, validation precedence, concurrency, and numeric precision.

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, declaring the capacity in which it acts. If either header is absent — or, in the case of `X-User-ID`, present but empty or whitespace only — or if `X-User-Role` names something other than one of the six roles below, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). If the headers are well-formed but the named role is not among the roles the target endpoint admits, the rejection is `ERR_UNAUTHORIZED` (HTTP 403).

The six recognised roles are `PlatformAdmin`, `PrivacyOfficer`, `ComplianceApprover`, `DataSteward`, `SecurityEngineer`, and `Consumer`.

- A `PlatformAdmin` operates the compliance platform itself: it registers app products, registers consumers, registers geofence zones, amends a product's size and HIPAA-ratio inputs, and drives the logical clock.
- A `PrivacyOfficer` owns applicability assessments, privacy policy drafting, vendor agreements, and the fulfilment of consumer rights requests including downstream deletion tasks.
- A `ComplianceApprover` is the independent second pair of eyes: it approves or returns applicability assessments and publishes or returns privacy policy versions.
- A `DataSteward` maintains the data element inventory, the processing purpose catalogue, the element-purpose mappings, and the geofence campaigns.
- A `SecurityEngineer` records breaches, assesses their reportability, notifies, retracts, and documents the security risk program.
- A `Consumer` is the natural person whose data is at stake; it grants and withdraws consent, files rights requests, and resubmits identity information.

Identity semantics differ by role, and the difference is load-bearing. When `X-User-Role` is `PlatformAdmin`, `PrivacyOfficer`, `ComplianceApprover`, `DataSteward`, or `SecurityEngineer`, `X-User-ID` is an opaque operator identifier that is not tied to any persisted entity. The server records it where a transition says to — as `submitted_by_user_id` and `approved_by_user_id` on an applicability assessment, and as `authored_by_user_id` and `published_by_user_id` on a privacy policy version — and it compares two such recorded identifiers against each other for segregation of duties, but it never compares an operator identifier to any entity's `id`. When `X-User-Role` is `Consumer`, by contrast, `X-User-ID` is the `id` of the acting `Consumer` row; ownership checks on any resource that references a `Consumer` compare that resource's `consumer_id` to `X-User-ID`.

That ownership check is enforced on the four consumer-driven write operations — granting consent, withdrawing consent, filing a rights request, and resubmitting identity information. A `Consumer` caller whose `X-User-ID` does not equal the `consumer_id` of the consent record or rights request being acted on is rejected with `ERR_CONSUMER_SCOPE_VIOLATION` (HTTP 403).

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
- The `api_request_timestamp` is a server-generated ISO 8601 UTC timestamp with three fractional digits. It is request metadata rather than a domain instant, and is therefore read from real wall-clock UTC and *not* from the logical clock of §2.5.
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

List endpoints are paginated through two query parameters. `limit` caps the number of rows returned; when omitted it defaults to 10, its minimum accepted value is 1 and its maximum accepted value is 100. `offset` skips that many rows from the front of the result set, defaults to 0, and has no upper bound. A value outside the accepted range for either parameter, or one that is not a base-ten integer, is a malformed request and is rejected with `ERR_INVALID_REQUEST`; a parameter supplied as an empty string simply falls back to its default.

Unless a specific endpoint says otherwise, list results are ordered by `created_at` ascending, and rows sharing an identical `created_at` — which the logical clock of §2.5 makes commonplace — are broken by ascending insertion order, so the row created first sorts first. That same `created_at`-then-insertion-order rule breaks ties wherever this document orders a cascade, a fan-out or a classification pass by `created_at`.

List responses carry `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the envelope. `total_count` is the number of rows matching the filters before pagination; `has_more` is true when rows remain beyond the returned page.

Most list endpoints also accept domain filters, which are documented alongside the workflows in §3 and summarised here for convenience: app products by `applicability_status`; applicability assessments by `app_product_id` and `state`; data elements by `app_product_id`, `derived_from_element_id`, and `status`; processing purposes by `app_product_id` and `activity_kind`; element-purpose mappings by `data_element_id`, `processing_purpose_id`, `vendor_id`, and `status`; consumers by `app_product_id`; consent records by `consumer_id` and `record_state`; privacy policy versions by `app_product_id`, `applicability_assessment_id`, and `state`; consumer requests by `consumer_id`, `state`, and `request_kind`; deletion tasks by `consumer_request_id`, `vendor_id`, and `state`; vendors by `app_product_id`, `subprocessor_of_id`, and `agreement_state`; geofence zones by `app_product_id` and `prohibition_rule`; geofence campaigns by `geofence_zone_id`, `processing_purpose_id`, and `state`; breach incidents by `app_product_id` and `state`; and security risk assessments by `app_product_id`, `state`, and `risk_tier`.

### 2.4. Common Resource Properties

Every persisted resource in the system — app products, applicability assessments, data elements, processing purposes, element-purpose mappings, consumers, consent records, privacy policy versions, consumer requests, deletion tasks, vendors, geofence zones, geofence campaigns, breach incidents, and security risk assessments — carries the same four system-managed properties:

- **`id`** (string): a server-minted UUID. It carries no type prefix and is never supplied by the client.
- **`created_at`** (string): the ISO 8601 UTC instant at which the row was created, rendered with three fractional digits (for example `2026-08-01T00:00:00.000Z`).
- **`updated_at`** (string): the ISO 8601 UTC instant of the row's most recent modification, in the same format. Every mutation refreshes it, including mutations the server performs on its own initiative as part of a cascade.
- **`version`** (integer): a monotonic counter that reads 1 on the freshly created row and increments by one on every subsequent mutation of the row, whether that mutation was requested directly or applied by a cascade.

No entity in this system omits `updated_at` or `version`; all fifteen resource types carry the full set.

Two version increments are relied upon by clients and are therefore called out explicitly. Approving an applicability assessment, and creating a privacy policy version, each increment the owning app product's `version` by one; amending the product's size or ratio inputs does the same. Creating a consent record increments the owning consumer's `version` by one. These are the increments that the stale-version guards of §2.8 test against.

Fields marked as computed or system-managed anywhere in this specification are never accepted from a request body. Supplying one is a malformed request and yields `ERR_INVALID_REQUEST`. A body key that is neither computed nor a declared input of the operation being invoked — an immutable creation-time field such as `element_key`, `vendor_name` or `assessment_label` offered to an amendment endpoint, or simply an unrecognised key — is neither applied nor rejected: it is silently ignored.

### 2.5. The Logical Compliance Clock

Deadlines, windows, cooldowns and stamped instants in this system are all measured against a server-held **logical clock** rather than real wall-clock time, so that compliance timelines are reproducible. Before any client sets it, the logical clock reads exactly `2026-08-01T00:00:00Z`; it never falls back to real time. A `PlatformAdmin` may move it to an explicit UTC instant by supplying `to_iso8601`; the response reports the resulting `current_utc`. Every computed timestamp, every deadline derivation, and every window or cooldown comparison in the rest of this document reads the logical clock.

Day arithmetic is whole-day arithmetic performed on exact UTC instants with no timezone shift: adding thirty days to an instant advances it by exactly thirty times twenty-four hours. Where a rule compares a date rather than an instant — the effective-date checks on policy publication, for example — the comparison uses the logical clock's calendar date in UTC.

### 2.6. Identifier Resolution and the Product Boundary

Requests that name resources are resolved in a fixed order, so that a client always learns about the outermost problem first. Path identifiers are validated left to right, and the first segment that resolves to nothing terminates the request with a 404. Which 404 is returned depends on the entity the segment addresses: an unresolved app product yields `ERR_APP_PRODUCT_NOT_FOUND`, an unresolved consumer `ERR_CONSUMER_NOT_FOUND`, an unresolved vendor `ERR_VENDOR_NOT_FOUND`, an unresolved data element `ERR_DATA_ELEMENT_NOT_FOUND`, an unresolved processing purpose `ERR_PURPOSE_NOT_FOUND`, and an unresolved row of any other type — applicability assessment, element-purpose mapping, consent record, privacy policy version, consumer request, deletion task, geofence zone, geofence campaign, breach incident, or security risk assessment — yields the generic `ERR_RESOURCE_NOT_FOUND`.

Foreign keys inside a request body are resolved after the body's shape has been validated, and they too are resolved in a fixed order rather than in whatever order the client happened to serialise them: `app_product_id`, then `applicability_assessment_id`, then `consumer_id`, then `data_element_id`, then `derived_from_element_id`, then `processing_purpose_id`, then `vendor_id`, then `subprocessor_of_id`, then `geofence_zone_id`, then `consumer_request_id`. Each unresolved key maps to the same per-entity 404 code listed above.

Once every key resolves, the system checks that they all belong to the *same* app product. Compliance artefacts never span products: the data element and the processing purpose named by one element-purpose mapping must share an app product, the vendor named by that mapping must belong to the same product, a derivation parent must be an element of the same product, a subprocessor's parent vendor must belong to the same product, and a geofence campaign's processing purpose must belong to the same product as its geofence zone. A body that mixes products is rejected with `ERR_CROSS_PRODUCT_REFERENCE` (HTTP 409). This check guards five creation operations: element-purpose mapping creation, data element creation, vendor creation, geofence campaign creation, and privacy policy version creation.

### 2.7. Validation Precedence

Many operations in this system are guarded by several checks at once, and which error a client sees is determined by a single global precedence order. Checks are evaluated in the order below and the first failure short-circuits the request. Lower-numbered checks therefore mask higher-numbered ones: a caller with the wrong role never learns that its payload was also malformed, and a caller acting on a policy that is not under review never learns that the policy's completeness score was also too low. The conditions that trigger each check are described in the workflow narratives of §3; what this list fixes is the *order*.

1. Authentication — both headers present, `X-User-Role` naming a declared role — `ERR_UNAUTHENTICATED`, 401, on every endpoint.
2. Role authorisation — `ERR_UNAUTHORIZED`, 403, on every endpoint.
3. Path identifier resolution, left to right — the per-entity 404 codes of §2.6, on every endpoint carrying an identifier segment.
4. Request-body shape: required fields present, enum values drawn from the declared members, integers inside their declared ranges, and no computed or system field supplied — `ERR_INVALID_REQUEST`, 400, on every creation and amendment endpoint. Two *cross-field* relations also yield `ERR_INVALID_REQUEST` but are deliberately evaluated later than the rest of the shape validation, after the body's foreign keys have resolved: `named_third_party_count` not exceeding `disclosed_third_party_count` on privacy policy version creation, evaluated after checks 5, 6 and 9 so that a cross-product reference or a stale product version masks it, and `affected_state_max_count` not exceeding `affected_consumer_count` on breach incident creation, evaluated once `app_product_id` has resolved. A request that carries no body at all is read as an empty JSON object, which is exactly what the action endpoints declaring no input fields expect; a body that is present but is not a JSON object, or is not valid JSON, is `ERR_INVALID_REQUEST`.
5. Body foreign-key resolution in the order given in §2.6 — the per-entity 404 codes, on every creation and amendment endpoint carrying foreign keys.
6. Same-product referential integrity — `ERR_CROSS_PRODUCT_REFERENCE`, 409, on the five creation operations listed in §2.6.
7. Consumer ownership scope — `ERR_CONSUMER_SCOPE_VIOLATION`, 403, on consent granting, consent withdrawal, rights-request filing, and identity resubmission.
8. From-state admissibility: the target must currently sit in a state from which the requested transition is declared. A data element action that requires an `ACTIVE` element fails with `ERR_ELEMENT_RETIRED`; a policy publish or return-to-draft on a version not in `IN_REVIEW` fails with `ERR_POLICY_NOT_IN_REVIEW`; a deletion-task notify or reissue whose vendor agreement is not `EXECUTED` fails with `ERR_VENDOR_AGREEMENT_NOT_EXECUTED`, and on those two endpoints the vendor test runs *ahead of* the task's own from-state test, so a task whose vendor has since been terminated reports that code even when the task also sits in a state the transition does not admit; a target already sitting in one of its terminal states fails with `ERR_ALREADY_TERMINAL`; every other from-state mismatch fails with `ERR_INVALID_STATE`. All 409, on every action endpoint.
9. Stale parent version — `ERR_STALE_PRODUCT_VERSION` on privacy policy version creation and `ERR_STALE_CONSUMER_VERSION` on consent record creation, both 412. See §2.8.
10. Segregation of duties — `ERR_SEGREGATION_OF_DUTIES`, 403, on applicability assessment approval and policy publication. See §2.9.
11. Geofence prohibition — `ERR_GEOFENCE_PROHIBITED`, 403, on campaign activation.
12. Geofence standoff — `ERR_GEOFENCE_STANDOFF_VIOLATION`, 422, on campaign activation.
13. Minor sale prohibition — `ERR_MINOR_SALE_PROHIBITED`, 403, on consent granting.
14. Consent bundling prohibition — `ERR_CONSENT_BUNDLING_PROHIBITED`, 422, on consent granting.
15. Collection consent prerequisite — `ERR_COLLECTION_CONSENT_REQUIRED`, 409, on consent granting.
16. Sharing consent prerequisite — `ERR_SHARING_CONSENT_REQUIRED`, 409, on consent granting.
17. Element key uniqueness — `ERR_DUPLICATE_ELEMENT_KEY`, 409, on data element creation.
18. Other per-product uniqueness — `ERR_DUPLICATE_PURPOSE_KEY` on processing purpose creation, `ERR_DUPLICATE_CONSUMER_REF` on consumer registration, `ERR_DUPLICATE_VENDOR_NAME` on vendor registration, all 409.
19. Derivation source coherence — `ERR_DERIVATION_SOURCE_REQUIRED`, 422, on data element creation and amendment.
20. Derivation acyclicity — `ERR_INFERENCE_CYCLE`, 422, on data element creation and amendment.
21. Derivation depth ceiling — `ERR_INFERENCE_DEPTH_EXCEEDED`, 422, on data element creation and amendment.
22. Derivation parent liveness on reinstatement — `ERR_ELEMENT_PARENT_RETIRED`, 409, on data element reinstatement.
23. Assessment revision ceiling — `ERR_ASSESSMENT_REVISION_LIMIT`, 409, on assessment revision.
24. Verification round ceiling — `ERR_VERIFICATION_ROUNDS_EXHAUSTED`, 409, on requesting more identity information.
25. Deletion-task attempt ceiling — `ERR_TASK_ATTEMPT_LIMIT`, 409, on deletion-task notify and on deletion-task reissue.
26. Single extension rule — `ERR_EXTENSION_ALREADY_GRANTED`, 409, on taking the response-deadline extension.
27. Approved-assessment prerequisite — `ERR_ASSESSMENT_NOT_APPROVED`, 409, on policy submit-for-review and on security risk assessment finalisation.
28. Determined applicability prerequisite — `ERR_APPLICABILITY_UNDETERMINED`, 409, on element-purpose mapping activation.
29. Vendor named for a disclosing purpose — `ERR_VENDOR_REQUIRED_FOR_DISCLOSURE`, 422, on element-purpose mapping creation and on mapping activation.
30. Vendor agreement sufficiency — `ERR_VENDOR_AGREEMENT_DEFICIENT`, 409, on element-purpose mapping activation.
31. Flow-down clause present — `ERR_FLOW_DOWN_CLAUSE_MISSING`, 422, on vendor agreement execution.
32. Audit rights clause present — `ERR_AUDIT_RIGHTS_MISSING`, 422, on vendor agreement execution.
33. Subprocessor parent executed — `ERR_SUBPROCESSOR_PARENT_NOT_EXECUTED`, 409, on vendor agreement execution.
34. Policy currency prerequisite — `ERR_POLICY_LAPSED`, 409, on element-purpose mapping activation and on geofence campaign activation.
35. Effective date not in the past — `ERR_EFFECTIVE_DATE_IN_PAST`, 422, on policy publication.
36. Policy effectivity window disjointness — `ERR_POLICY_WINDOW_OVERLAP`, 409, on policy publication.
37. Campaign window ordering — `ERR_WINDOW_END_BEFORE_START`, 422, on campaign creation.
38. Campaign window exclusivity on the zone — `ERR_CAMPAIGN_WINDOW_CONFLICT`, 409, on campaign activation.
39. Zone cooldown — `ERR_ZONE_COOLDOWN_ACTIVE`, 409, on campaign activation.
40. Verification window still open — `ERR_VERIFICATION_WINDOW_EXPIRED`, 409, on identity resubmission.
41. Verification token match — `ERR_VERIFICATION_TOKEN_MISMATCH`, 422, on rights-request verification.
42. Response deadline not passed — `ERR_RESPONSE_DEADLINE_PASSED`, 409, on rights-request fulfilment.
43. No outstanding deletion tasks — `ERR_DELETION_TASKS_OUTSTANDING`, 409, on rights-request fulfilment.
44. Notification deadline not passed — `ERR_NOTIFICATION_DEADLINE_PASSED`, 409, on breach notification.
45. Media notice accompaniment — `ERR_MEDIA_NOTICE_REQUIRED`, 422, on breach notification.
46. Policy completeness threshold — `ERR_POLICY_COMPLETENESS_BELOW_THRESHOLD`, 422, on policy publication.
47. Remediation plan requirement — `ERR_REMEDIATION_PLAN_REQUIRED`, 422, on security risk assessment finalisation.
48. Active inventory prerequisite — `ERR_NO_ACTIVE_ELEMENTS`, 409, on applicability assessment submission.

### 2.8. Stale-Version Guards on Product and Consumer Writes

Two creation operations legitimately displace an incumbent record, and both are therefore protected by an optimistic-concurrency guard against a client acting on a parent it has not re-read.

Drafting a privacy policy version — `POST /health-data/privacy-policy-versions` — must carry `expected_app_product_version`, a required (never optional) field holding the app product `version` the author last observed. If it does not equal the product's current `version`, the request is rejected with `ERR_STALE_PRODUCT_VERSION` (HTTP 412). The rationale is that a new policy version supersedes the incumbent on publication, so its drafted content is only meaningful against the product state the author described; when an assessment approval or an earlier publication has since rewritten the product's `applicability_status` or `policy_compliance_state`, the drafted text no longer describes the product it claims to describe.

Opening a consent record — `POST /health-data/consent-records` — must carry `expected_consumer_version`, likewise required, holding the consumer `version` whose consent posture the caller intends to replace. A mismatch with the consumer's current `version` is rejected with `ERR_STALE_CONSUMER_VERSION` (HTTP 412), because a stale version means the posture about to be superseded is not the posture the caller observed.

No other endpoint in this system accepts a version field, and none applies a concurrency check.

### 2.9. Segregation of Duties

Two decisions in the compliance workflow require a second pair of eyes, and the system enforces that mechanically by comparing recorded operator identifiers. Approving an applicability assessment requires that the approver's `X-User-ID` differ from the `submitted_by_user_id` recorded when the assessment was submitted. Publishing a privacy policy version requires that the publisher's `X-User-ID` differ from the `authored_by_user_id` recorded when the version was drafted. Either violation is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403). Note that the role check comes first: a `PrivacyOfficer` attempting to approve its own assessment is stopped by `ERR_UNAUTHORIZED` because approval is reserved to `ComplianceApprover`, and the segregation check bites only when a `ComplianceApprover` account was also the submitter or author.

### 2.10. Precision, Scoring and Monetary Units

Monetary amounts in this system are integer counts of cents. `annual_revenue_cents`, `exposure_cents`, `exposure_contribution_cents` and the per-consumer exposure constant are all whole cents, and no rounding is ever applied to them.

Two derived scores carry fractional precision, and both are computed with **exactly one** rounding step applied at the very end, using round-half-up. A privacy policy version's `completeness_score` is rounded to one decimal place. A security risk assessment's `residual_risk_score` is rounded to two decimal places. In both cases the intermediate terms — component ratios, weighted domain terms — are carried at full precision and are *not* rounded before being combined; rounding each intermediate and then combining produces a different answer for some inputs and is incorrect.

`hipaa_covered_transaction_ratio` is a fraction between 0.00 and 1.00 inclusive, stored with exactly two decimal places — a submitted value carrying more decimals is quantised to two places half-up on the way in, so 0.955 is stored, echoed and compared as 0.96 — and the threshold comparisons that read it compare the stored two-decimal value using an at-least test. Distances and standoffs are whole metres. Element counts, hop counts, revision counts and attempt counts are non-negative integers. Where a rule rounds a ratio *up* to a whole number, it takes the smallest integer that is not less than the value.

### 2.11. Derived Product Posture and Cascade Discipline

An app product is the aggregate root of the compliance model, and it carries a set of read-only counters and posture enums that the server maintains. `active_element_count` is the number of that product's data elements whose `status` is `ACTIVE`. `regulated_element_count` is the number of those `ACTIVE` elements whose `chd_classification` is `CHD` or `CHD_BY_INFERENCE`. `active_share_consent_count` is the number of consent records belonging to the product's consumers whose `record_state` is `ACTIVE` and whose `sharing_state` is `GRANTED`. `exposure_cents` is the sum of `exposure_contribution_cents` over the product's breach incidents whose `state` is `REPORTABLE` or `NOTIFIED`. `small_business_flag`, `applicability_status`, `regulated_scope` and `compliance_deadline_date` are described in §3.1.

`policy_compliance_state` takes one of three values. It is `NO_POLICY` while no privacy policy version for the product has ever reached `PUBLISHED`. It is `CURRENT` while exactly one privacy policy version for the product sits in `PUBLISHED`. It is `LAPSED` when the most recently published version has been moved to `SUPERSEDED_PENDING_UPDATE`. `security_program_state` likewise takes three values: `NONE` while no security risk assessment for the product has reached `FINALIZED`; `CURRENT` when the `FINALIZED` assessment with the greatest `created_at` carries a `risk_tier` of `LOW` or `MODERATE`; and `STALE` when that same assessment carries a `risk_tier` of `HIGH` or `CRITICAL`.

Cascades are applied **synchronously, inside the originating request, in the declared hop order**, and each hop's precondition is evaluated against the state left behind by the previous hop. A hop that mutates a row refreshes that row's `updated_at` and increments its `version`, exactly as a client-driven mutation would; a counter recomputation on the app product is such a mutation. Recomputed and derived values are compared against the stored ones before being written, though, and a recomputation, refresh or posture assignment that leaves every stored value exactly as it was is not a mutation at all: it leaves that row's `updated_at` and `version` untouched. Recomputing a counter that does not move, refreshing `small_business_flag` to the value it already held, re-deriving a data element's `chd_classification` to the same class, or setting `policy_compliance_state` to `CURRENT` on a product already `CURRENT` therefore bumps nothing. Where a cascade fans out over several sibling rows, the rows are processed in ascending `created_at` order so that the outcome is deterministic. The individual cascades — data element retirement, vendor agreement termination, consent withdrawal, deletion-task confirmation, rights-request fulfilment and denial, and breach retraction — are specified with their hops in §3.

A convenience read exposes the whole posture in one shape: `app_product_id`, `applicability_status`, `regulated_scope`, `active_element_count`, `regulated_element_count`, `active_share_consent_count`, `policy_compliance_state`, `security_program_state`, `exposure_cents`, plus two counts computed on demand — `open_request_count`, the number of rights requests belonging to the product's consumers whose `state` is neither `FULFILLED` nor `DENIED`, and `outstanding_deletion_task_count`, the number of deletion tasks whose `state` is `PENDING`, `NOTIFIED` or `FAILED` under *any* rights request of the product's consumers, closed requests included rather than only the open ones just counted.

## 3. Business Logic & Workflows

### 3.1. Registering a Product and Determining Applicability

A `PlatformAdmin` opens the file on a consumer health application by registering it with its trade name in `product_name`, the operating legal entity in `company_legal_name`, the two-letter US state code of its principal place of business in `primary_state_code` (one of `WA`, `NV`, `CT`, `CA`, or `TX`), the number of natural persons whose data it processes per year in `consumer_count`, the prior-year gross revenue in whole cents in `annual_revenue_cents`, and the fraction of its data flows that arise from HIPAA covered functions in `hipaa_covered_transaction_ratio`. Both `consumer_count` and `annual_revenue_cents` must be zero or greater. The product begins life with `applicability_status` at `UNDETERMINED`, `regulated_scope` at `NONE`, `policy_compliance_state` at `NO_POLICY`, `security_program_state` at `NONE`, a null `compliance_deadline_date`, every counter at zero, and `small_business_flag` already computed at registration from the two size inputs by the rule of step one below rather than left at false. The size and ratio inputs — along with `product_name` — remain amendable by a `PlatformAdmin` afterwards, and each amendment recomputes `small_business_flag` and bumps the product's `version`; the amendment endpoint bumps that `version` unconditionally, even when the submitted values match the stored ones or the body is empty.

The regulatory track is not asserted by the operator; it is determined by a reviewed artefact. A `PrivacyOfficer` opens an **applicability assessment** against the product by supplying `app_product_id`, the operator's self-declared HIPAA posture in `entity_status_claim` (one of `COVERED_ENTITY`, `BUSINESS_ASSOCIATE`, or `NOT_COVERED`), and free-text rationale in `analyst_note`. The assessment is created in `DRAFT` with `revision_count` at zero, its `determination`, `regulated_scope`, `compliance_deadline_date`, `submitted_by_user_id`, `approved_by_user_id` and `return_reason` all unset, and both snapshot counters at zero.

Submitting the assessment moves it `DRAFT → SUBMITTED` and is the moment the determination is computed. Submission is admitted only from `DRAFT`, and only if the product has at least one data element whose `status` is `ACTIVE` — a product with an empty live inventory has nothing to analyse, and the attempt is refused with `ERR_NO_ACTIVE_ELEMENTS`. Submission stamps `submitted_by_user_id` with the caller's `X-User-ID` and refreshes the product's `small_business_flag` — which, per §2.11, bumps the product's `version` only if that flag actually changes value.

The determination itself is a four-step computation whose evaluation order is pinned. It *looks* circular — a product's track seems to depend on how much regulated data it holds, while which data is regulated seems to depend on the track — and the pinned order is what breaks the apparent circularity. No step may read a value produced by a later step.

**Step one** works only from the product's own input fields and the assessment's `entity_status_claim`. The `small_business_flag` is set to true when the product processes fewer than one hundred thousand consumers per year *and* its prior-year revenue is under twenty-five million dollars — that is, `consumer_count` strictly below 100000 and `annual_revenue_cents` strictly below 2500000000 — and false otherwise. Then the track: if the operator claims to be a `COVERED_ENTITY` or a `BUSINESS_ASSOCIATE` and its `hipaa_covered_transaction_ratio` is at least 0.95, the `determination` is `HIPAA_ONLY`; otherwise, if it makes one of those two claims and the ratio is at least 0.50, the `determination` is `DUAL_TRACK`; in every remaining case — including any claim of `NOT_COVERED` regardless of ratio, and a covered claim with a ratio below 0.50 — the `determination` is `CHD_REGULATED`.

**Step two** classifies every data element of the product as consumer health data or not, by the rules of §3.2. Step two must not read the `determination`; the classification of an element is a property of the element, not of the track.

**Step three** freezes two counts, taken over that product's data elements whose `status` is `ACTIVE` only. `active_element_count_snapshot` is the number of such rows, and `regulated_element_count_snapshot` is the number of them whose `chd_classification` is `CHD` or `CHD_BY_INFERENCE`. Retired elements are excluded from these two counts, and from these two counts only. Both snapshots are frozen even when the `determination` came out as `HIPAA_ONLY`, so that a later re-analysis can see what the inventory looked like.

**Step four** reads steps one and three and nothing else. If the `determination` is `HIPAA_ONLY`, the `regulated_scope` is `NONE` and `compliance_deadline_date` is null. Otherwise, if `regulated_element_count_snapshot` is zero, the `regulated_scope` is `NONE`. Otherwise, if `regulated_element_count_snapshot` is at least the value obtained by taking half of `active_element_count_snapshot` and rounding up to the next whole number, the `regulated_scope` is `FULL`. In the remaining case the `regulated_scope` is `PARTIAL`. Whenever the `determination` is anything other than `HIPAA_ONLY`, the deadline is set as well: a product whose `small_business_flag` is true gets the small-business deadline of `2026-06-30`, and every other product gets the standard deadline of `2026-03-31`.

A `ComplianceApprover` then either approves or returns the submitted assessment. Approval, admitted only from `SUBMITTED` and only when the approver's `X-User-ID` differs from the recorded `submitted_by_user_id`, advances it `SUBMITTED → APPROVED`, stamps `approved_by_user_id` with the approver's `X-User-ID`, and copies the determination onto the product: the product's `applicability_status` becomes the assessment's `determination`, its `regulated_scope` becomes the assessment's `regulated_scope`, and its `compliance_deadline_date` becomes the assessment's `compliance_deadline_date`. Any other assessment on the same product that was itself sitting in `APPROVED` is moved `APPROVED → SUPERSEDED`; that supersession changes no product field, because the approving assessment has already rewritten them all. Approval finally increments the product's `version` by one, which is the increment that invalidates any policy draft still holding the earlier value.

Returning the assessment, also admitted only from `SUBMITTED`, moves it `SUBMITTED → RETURNED` and records the approver's `return_reason` from the request body. A return deliberately leaves the product's `applicability_status` untouched — a rejected analysis must not disturb the incumbent track.

From `RETURNED`, the `PrivacyOfficer` may reopen the work, moving it `RETURNED → DRAFT`. Reopening increments `revision_count` by one and clears `determination`, `regulated_scope`, `compliance_deadline_date` and `submitted_by_user_id` back to null, so that resubmission recomputes everything from scratch. The two frozen snapshots are left as they were. This `RETURNED → DRAFT → SUBMITTED → RETURNED` loop is bounded: reopening is admitted only while `revision_count` is strictly below two, and the third attempt is refused with `ERR_ASSESSMENT_REVISION_LIMIT`. `SUPERSEDED` is the assessment's only terminal state.

### 3.2. The Data Element Inventory and Consumer Health Data Classification

A `DataSteward` declares each element the product collects with a stable machine key in `element_key`, a human-readable label in `display_name` that the privacy policy text will reuse, an acquisition channel in `source_kind` (`USER_PROVIDED`, `DEVICE_SENSOR`, `THIRD_PARTY`, or `DERIVED_INFERENCE`), and the health meaning the element itself carries in `health_signal_kind` (`DIAGNOSIS`, `TREATMENT`, `MEASUREMENT`, `REPRODUCTIVE`, `PRECISE_LOCATION`, `BIOMETRIC`, or `NON_HEALTH`), alongside the owning `app_product_id`. An element that the product processes solely inside a HIPAA covered function is flagged with `hipaa_flow_only`, which defaults to false when omitted. An inferred element names the element it was derived from in `derived_from_element_id`, which is null for anything the product collects directly.

The two derivation fields must agree with each other. A `source_kind` of `DERIVED_INFERENCE` requires a non-null `derived_from_element_id`, and a non-null `derived_from_element_id` requires a `source_kind` of `DERIVED_INFERENCE`; either half violated is rejected with `ERR_DERIVATION_SOURCE_REQUIRED`. Keys are unique within a product: an `element_key` already in use by another element of the same product whose `status` is `ACTIVE` or `RETIRED` is refused with `ERR_DUPLICATE_ELEMENT_KEY`. The same descriptive and classification inputs — `display_name`, `source_kind`, `health_signal_kind`, `derived_from_element_id`, `hipaa_flow_only` — remain amendable, and an amendment reclassifies the element and every element derived from it (the server in fact re-runs the classification pass over every element of the product, which settles the same classes) and refreshes the product's `regulated_element_count`. Amendment carries no from-state condition, so a `RETIRED` element may be amended exactly as an `ACTIVE` one and its `status` is left untouched; nor does amendment re-apply the same-product rule of §2.6, which guards element *creation* only, although a named `derived_from_element_id` must still resolve to some element.

Classification runs whenever an element is written, amended, retired or reinstated, and as step two of the applicability determination. It begins by resolving the derivation chain: the server walks `derived_from_element_id` upward until it reaches an element whose `derived_from_element_id` is null, and records the number of hops walked in `inference_depth`, which is zero for an element that is not derived at all. A walk that revisits an element it has already visited is a cycle and the write is refused with `ERR_INFERENCE_CYCLE`. A walk whose hop count would exceed five hops is refused with `ERR_INFERENCE_DEPTH_EXCEEDED`; five hops is the deepest inference chain the product may declare.

Elements are then classified in ascending `inference_depth`, ties broken by ascending `created_at`, so that a parent's classification is always already settled when its child is evaluated. Each element's `chd_classification` is decided by the first matching branch of the following ladder, and the ladder is ordered:

1. An element flagged `hipaa_flow_only` whose `source_kind` is anything other than `THIRD_PARTY` is `NON_CHD` — it lives inside the HIPAA perimeter and the consumer health regime does not reach it. Note the deliberate exception: a `THIRD_PARTY`-sourced element does *not* get this exemption even when flagged, because data arriving from outside cannot be assumed to have stayed inside the covered function.
2. Otherwise, an element whose `health_signal_kind` is `DIAGNOSIS`, `TREATMENT`, `MEASUREMENT`, `REPRODUCTIVE`, or `BIOMETRIC` is `CHD`. These five are the direct health signals.
3. Otherwise, an element whose `health_signal_kind` is `PRECISE_LOCATION` is `CHD_BY_INFERENCE` — location is not itself a health fact, but at sufficient precision it reveals one.
4. Otherwise, an element whose `inference_depth` is zero is `NON_CHD`.
5. Otherwise — that is, for a derived element with no health signal of its own — the element is `CHD_BY_INFERENCE` when its parent element's `chd_classification` is `CHD` or `CHD_BY_INFERENCE`.
6. In every remaining case the element is `NON_CHD`.

Creating an element runs this classification, writes `inference_depth` and `chd_classification`, and refreshes both `active_element_count` and `regulated_element_count` on the product. Elements start with `status` at `ACTIVE` and a null `retired_reason`. The classification pass counts as part of creating the row rather than as a later mutation of it, so the creation response reports `version` 1 and an `updated_at` equal to `created_at` however much the pass rewrote.

Retiring an element, which a `DataSteward` does with a `retired_reason` in the body, is the system's most far-reaching inventory cascade. The first hop moves the named element `ACTIVE → RETIRED` and records the supplied `retired_reason`. The second hop propagates down the derivation tree: every element whose `derived_from_element_id` names a just-retired element and whose `status` is still `ACTIVE` is itself moved `ACTIVE → RETIRED` with `retired_reason` set to `SOURCE_ELEMENT_RETIRED`, applied transitively along the whole derivation chain and processed in ascending `created_at` order — an inference cannot survive the withdrawal of the signal it was inferred from. The third hop follows from the second: because that set of elements became `RETIRED`, every element-purpose mapping whose `data_element_id` names any element retired by hops one or two, and whose `status` is `PROPOSED`, `ACTIVE` or `SUSPENDED`, is moved to `RETIRED`. The fourth hop follows from the third: because the retired mapping set changed, the product's `active_element_count` and `regulated_element_count` are both recomputed.

Reinstatement runs the loop backwards, `RETIRED → ACTIVE`, and is admitted only when the element's `derived_from_element_id` is null or the parent element it names currently has `status` `ACTIVE`; reinstating a child under a still-retired parent is refused with `ERR_ELEMENT_PARENT_RETIRED`. Reinstatement clears `retired_reason` to null, recomputes `chd_classification` and `inference_depth`, and refreshes `active_element_count` and `regulated_element_count`. What reinstatement does **not** do is revive the mappings that hop three retired; those are gone for good and must be proposed again. A data element has no terminal state — it may cycle `ACTIVE → RETIRED → ACTIVE` indefinitely.

### 3.3. Processing Purposes and the Element-to-Purpose Wiring

A `DataSteward` declares each **processing purpose** the product pursues, naming the owning `app_product_id`, a stable `purpose_key` unique within the product, the text that will appear in the privacy policy in `description_text`, the business character of the processing in `purpose_kind` (`PRIMARY_SERVICE`, `ANALYTICS`, `ADVERTISING`, `RESEARCH`, or `SALE`), and the regulated activity it performs on the data in `activity_kind` (`COLLECT`, `SHARE`, or `SELL`). A `purpose_key` already taken on the same product is refused with `ERR_DUPLICATE_PURPOSE_KEY`.

Three purpose fields are derived on write and are never supplied by the client. `consent_axis` simply mirrors `activity_kind`: a `COLLECT` purpose consumes the collection axis, a `SHARE` purpose the sharing axis, and a `SELL` purpose the sale axis. `requires_separate_consent` is true when the `activity_kind` is `SHARE` or `SELL`, or when the `purpose_kind` is `ADVERTISING`, `RESEARCH`, or `SALE` — either condition alone suffices — and false otherwise. `third_party_disclosure_required` is true precisely when the `activity_kind` is `SHARE` or `SELL`, and when it is true, any mapping onto that purpose must name a recipient vendor.

The wiring between inventory and purposes is the **element-purpose mapping**. A `DataSteward` proposes one by naming `data_element_id`, `processing_purpose_id`, the granularity at which the pairing is disclosed in `disclosure_specificity` (`ELEMENT_NAMED` or `CATEGORY_NAMED`), and, for a disclosing purpose, the recipient in `vendor_id`. The `vendor_id` is null when the purpose's `activity_kind` is `COLLECT` — a convention rather than an enforced rule, since nothing rejects a resolvable same-product `vendor_id` offered against a `COLLECT` purpose and it is stored exactly as supplied; when the purpose's `third_party_disclosure_required` is true and no `vendor_id` is supplied, the proposal is refused with `ERR_VENDOR_REQUIRED_FOR_DISCLOSURE`. A mapping is created with `status` `PROPOSED`, a null `suspension_reason`, and `regulated_flag` computed from the referenced element: true when that element's `chd_classification` is `CHD` or `CHD_BY_INFERENCE`, false otherwise.

Activation is where a proposed pairing becomes a live data flow, and it carries the heaviest gate in the system. A mapping may be activated `PROPOSED → ACTIVE` or resumed `SUSPENDED → ACTIVE`; either way, the referenced data element's `status` must be `ACTIVE`, the product's `applicability_status` must be `DUAL_TRACK` or `CHD_REGULATED` — an `UNDETERMINED` or `HIPAA_ONLY` product has no consumer-health-data regime under which to authorise the flow, and the attempt is refused with `ERR_APPLICABILITY_UNDETERMINED` — and the product's `policy_compliance_state` must not be `LAPSED`, failing which the refusal is `ERR_POLICY_LAPSED`. When the referenced purpose's `third_party_disclosure_required` is true, two further conditions apply: the mapping's `vendor_id` must be non-null, on pain of `ERR_VENDOR_REQUIRED_FOR_DISCLOSURE`, and the named vendor's `agreement_state` must be `EXECUTED` with `agreement_compliance` `COMPLIANT`, on pain of `ERR_VENDOR_AGREEMENT_DEFICIENT`. Activation from `PROPOSED` recomputes `regulated_flag` from the element's current `chd_classification`; resumption from `SUSPENDED` clears `suspension_reason` back to null. The mapping may cycle `ACTIVE → SUSPENDED → ACTIVE` without limit.

Suspension, admitted only from `ACTIVE`, records the operator's `suspension_reason` from the body and moves the mapping `ACTIVE → SUSPENDED`. The same transition is also driven by the vendor-termination cascade of §3.4, in which case `suspension_reason` is set to `VENDOR_AGREEMENT_TERMINATED` rather than taken from a body.

Retirement is permanent and reachable from all three non-terminal states. Retiring from `PROPOSED` moves the mapping `PROPOSED → RETIRED`; retiring from `ACTIVE` moves it `ACTIVE → RETIRED`; retiring from `SUSPENDED` moves it `SUSPENDED → RETIRED`. In every case, `suspension_reason` is set to the reason supplied in the body — an optional field on the retire endpoint, so a retirement that omits it leaves whatever `suspension_reason` the mapping already carried, null included — or to `SOURCE_ELEMENT_RETIRED` when the retirement was driven by the data element cascade of §3.2. Retiring from `ACTIVE` additionally recomputes the product's `regulated_element_count`, because a live regulated flow has just ceased; retirement from `PROPOSED` or `SUSPENDED` does not, because neither was contributing a live flow. `RETIRED` is the mapping's terminal state.

### 3.4. Vendor and Processor Agreements

A `PrivacyOfficer` registers each **vendor** the product engages against the owning `app_product_id`, with its legal name in `vendor_name` — unique within the product, on pain of `ERR_DUPLICATE_VENDOR_NAME` — and the role it plays with respect to the data in `vendor_kind` (`PROCESSOR`, `THIRD_PARTY_RECIPIENT`, or `PURCHASER`). A vendor that was itself engaged by another vendor names its engager in `subprocessor_of_id`, which is null for a directly-engaged vendor. Three contract clauses are recorded as booleans, each defaulting to false when omitted: `flow_down_clause`, meaning the contract obliges the vendor to impose equivalent terms on its own subprocessors; `audit_rights_clause`, meaning the operator holds inspection and audit rights; and `sale_authorization_clause`, meaning the contract authorises the vendor to purchase consumer health data. The number of days the vendor contractually has to confirm a deletion instruction is recorded in `deletion_sla_days`, which defaults to 30 and must be between 1 and 90 inclusive. The four clause and SLA fields remain amendable while the agreement is still in `DRAFT`, and only then: an amendment aimed at an `EXECUTED` agreement is refused with `ERR_INVALID_STATE` and one aimed at a `TERMINATED` agreement with `ERR_ALREADY_TERMINAL`.

Agreements begin with `agreement_state` at `DRAFT`, a null `executed_at` and a null `terminated_at`. Whenever a vendor is written, amended, or executed, its `agreement_compliance` is recomputed and is `COMPLIANT` only when `flow_down_clause` is true *and* `audit_rights_clause` is true *and*, additionally, either the `vendor_kind` is something other than `PURCHASER` or the `sale_authorization_clause` is true. In every other case it is `DEFICIENT`, which is also its default at creation.

Execution moves the vendor `DRAFT → EXECUTED`, stamps `executed_at` with the logical clock, and recomputes `agreement_compliance`. Three conditions gate it, and each has its own code: `flow_down_clause` must be true, otherwise `ERR_FLOW_DOWN_CLAUSE_MISSING`; `audit_rights_clause` must be true, otherwise `ERR_AUDIT_RIGHTS_MISSING`; and `subprocessor_of_id` must be null or name a parent vendor whose own `agreement_state` is already `EXECUTED`, otherwise `ERR_SUBPROCESSOR_PARENT_NOT_EXECUTED`. A subprocessor can never be brought live ahead of the vendor that engaged it.

Termination is the five-hop cascade that makes the vendor relationship structurally load-bearing, and every hop follows from the one before it. Hop one moves the vendor `EXECUTED → TERMINATED` and stamps `terminated_at` with the logical clock. Hop two, because this vendor's agreement has ended, moves every element-purpose mapping whose `vendor_id` names this vendor and whose `status` is `ACTIVE` from `ACTIVE → SUSPENDED`, with `suspension_reason` set to `VENDOR_AGREEMENT_TERMINATED`. Hop three, because at least one `ACTIVE` mapping was suspended by hop two, moves the privacy policy version on the same product whose `state` is `PUBLISHED` from `PUBLISHED → SUPERSEDED_PENDING_UPDATE` — the published text now describes a disclosure that no longer exists, so it is no longer an accurate policy. Hop four, because that policy left `PUBLISHED` in hop three, sets the product's `policy_compliance_state` to `LAPSED`. Hop five, because the product's `policy_compliance_state` became `LAPSED` in hop four, moves every geofence campaign whose zone belongs to that same product and whose `state` is `ACTIVE` from `ACTIVE → PAUSED`, with `pause_reason` set to `POLICY_LAPSED`, processing those campaigns in ascending `created_at` order. `TERMINATED` is the vendor's terminal state; there is no path back.

The knock-on effect of a lapse is worth stating plainly, because it is the intended serialisation point between vendor management and everything downstream: while the product's `policy_compliance_state` is `LAPSED`, no element-purpose mapping and no geofence campaign can be activated or resumed at all, and both attempts fail with `ERR_POLICY_LAPSED`. Publishing a fresh policy version is the only way out.

### 3.5. Consent Architecture: Three Axes, One Grant at a Time

A `PlatformAdmin` registers each **consumer** of the product with the owning `app_product_id`, an operator-side pseudonymous account reference in `external_ref` that must be unique within the product — a collision is refused with `ERR_DUPLICATE_CONSUMER_REF` — the two-letter state code of the person's residence in `residency_state_code` (one of `WA`, `NV`, `CT`, `CA`, `TX`), and the bracket used by the minor-sale prohibition in `age_band` (`ADULT`, `MINOR_13_16`, or `UNDER_13`). Registration mints a server-issued `verification_token`, which the consumer later presents to prove identity on a rights request, and initialises `deletion_completed_count` to zero; that counter tracks how many of the consumer's `DELETE` requests have reached `FULFILLED`.

Consent is held in a **consent record**, opened by a `PrivacyOfficer` or a `PlatformAdmin` for a named `consumer_id` and carrying the mandatory `expected_consumer_version` described in §2.8. A new record is created with all three axes at their unrequested defaults — `collection_state` `NOT_REQUESTED`, `sharing_state` `NOT_REQUESTED`, `sale_state` `NOT_REQUESTED` — with `record_state` `ACTIVE`, with all four instant fields (`collection_granted_at`, `sharing_granted_at`, `sale_authorized_at`, `last_withdrawn_at`) null, with `last_withdrawn_axis` unset, and with `processing_halt_deadline_at` null. Creating it also moves the consumer's incumbent record, if one exists with `record_state` `ACTIVE`, from `ACTIVE → SUPERSEDED`; and if that outgoing record's `sharing_state` was `GRANTED`, the product's `active_share_consent_count` is decremented by one. The consumer's `version` increments by one. `SUPERSEDED` is a consent record's terminal state, so any grant or withdrawal aimed at a superseded record is refused with `ERR_ALREADY_TERMINAL`.

The three axes are the heart of the consent architecture: separate consent for collection, for sharing, and for sale, each moving independently within the live record. Every grant and every withdrawal is a self-loop on the record — `ACTIVE → ACTIVE` — so the record's `record_state` remains `ACTIVE` throughout, and only the axis fields and their timestamps change. What ties them together is a strict dependency ladder in the granting direction and a strict cascade in the withdrawing direction.

A `Consumer` grants on exactly one axis at a time, naming it in the `axes` array of the request. Supplying two or more axes — or none — is bundled consent, which the regime forbids, and the call is refused with `ERR_CONSENT_BUNDLING_PROHIBITED`. The three grants differ in their prerequisites:

- Granting `COLLECT` requires the record's `collection_state` to be `NOT_REQUESTED` or `WITHDRAWN`. It sets `collection_state` to `GRANTED` and stamps `collection_granted_at` with the logical clock. It has no upstream dependency: collection is the first rung.
- Granting `SHARE` requires the record's `collection_state` to already be `GRANTED` — you cannot authorise disclosure of data you have not authorised the collection of, and the attempt is refused with `ERR_COLLECTION_CONSENT_REQUIRED` — and requires the record's own `sharing_state` to be `NOT_REQUESTED` or `WITHDRAWN`. It sets `sharing_state` to `GRANTED`, stamps `sharing_granted_at` with the logical clock, and increments the product's `active_share_consent_count` by exactly one.
- Granting `SELL` requires the record's `sharing_state` to already be `GRANTED`, failing which the refusal is `ERR_SHARING_CONSENT_REQUIRED`; requires the record's own `sale_state` to be `NOT_REQUESTED` or `REVOKED`; and requires the consumer's `age_band` to be `ADULT`. A sale authorisation for a consumer in the `MINOR_13_16` or `UNDER_13` band is prohibited outright and refused with `ERR_MINOR_SALE_PROHIBITED`. A successful grant sets `sale_state` to `AUTHORIZED` and stamps `sale_authorized_at` with the logical clock. Note that the sale axis uses `AUTHORIZED`/`REVOKED` rather than `GRANTED`/`WITHDRAWN`, reflecting the stronger authorisation the sale of health data requires.

An axis whose current value is not one of the values its grant admits — attempting to re-grant `COLLECT` while `collection_state` is already `GRANTED`, for instance — is a from-state mismatch and is refused with `ERR_INVALID_STATE`. Where several of these checks could fire at once on a `SELL` grant, the precedence of §2.7 settles which the caller sees: the from-state check first, then the minor-sale prohibition, then the bundling check, then the collection-consent prerequisite, then the sharing-consent prerequisite. That from-state check is reached only when the `axes` array names exactly one axis, there being no single axis to test otherwise, so a bundled or empty array falls straight through to the minor-sale prohibition — which fires whenever `SELL` appears anywhere in the array — and then to the bundling refusal.

Withdrawal moves down the same ladder, and it cascades. A `Consumer` names a single `axis` in the request. Every accepted withdrawal, whichever axis it names, records `last_withdrawn_axis` as that axis, stamps `last_withdrawn_at` with the logical clock, and sets `processing_halt_deadline_at` to fifteen days after `last_withdrawn_at` — the operator has that fortnight-and-a-day to stop the processing the withdrawn axis had authorised.

- Withdrawing `COLLECT` requires `collection_state` to currently be `GRANTED`. Hop one sets `collection_state` to `WITHDRAWN`, `last_withdrawn_axis` to `COLLECT`, and the two instant fields as above. Hop two, because collection consent was withdrawn, moves `sharing_state` from `GRANTED → WITHDRAWN` if it was `GRANTED`. Hop three, because sharing consent was withdrawn by hop two, moves `sale_state` from `AUTHORIZED → REVOKED` if it was `AUTHORIZED`. Hop four, because `sharing_state` left `GRANTED` in hop two, decrements the product's `active_share_consent_count` by one.
- Withdrawing `SHARE` requires `sharing_state` to currently be `GRANTED`. It sets `sharing_state` to `WITHDRAWN`, `last_withdrawn_axis` to `SHARE`, and the two instant fields; it moves `sale_state` from `AUTHORIZED → REVOKED` if it was `AUTHORIZED`; and it decrements the product's `active_share_consent_count` by one. It leaves `collection_state` alone — a consumer may keep using the product while refusing disclosure.
- Withdrawing `SELL` requires `sale_state` to currently be `AUTHORIZED`. It sets `sale_state` to `REVOKED`, `last_withdrawn_axis` to `SELL`, and the two instant fields, and it leaves both `collection_state` and `sharing_state` unchanged. Because `sharing_state` does not leave `GRANTED`, `active_share_consent_count` is untouched.

Attempting to withdraw an axis that is not currently granted is refused with `ERR_INVALID_STATE`. The product's `active_share_consent_count` is a conserved quantity: a `SHARE` grant increments it by exactly one and the compensating `SHARE` withdrawal decrements it by exactly one, so the counter always equals the number of live `ACTIVE` records on the product with `sharing_state` `GRANTED`.

A third path into the same record exists, driven not by the consumer but by fulfilment of a deletion right; it is described in §3.7.

### 3.6. Privacy Policy Versions and Disclosure Completeness

A privacy policy is not free-form text in this system but a scored artefact. A `PrivacyOfficer` drafts a **privacy policy version** naming the owning `app_product_id`, the `applicability_assessment_id` of the assessment whose determination the text was written against, an operator-facing label for the version in `version_label`, the disclosure granularity chosen for this version in `specificity_mode` (`ELEMENT_LEVEL` or `CATEGORY_LEVEL`), four counts describing what the text actually says, the ISO 8601 date on which the version takes effect in `effective_from`, and the mandatory `expected_app_product_version` of §2.8.

The four counts are the raw material of the completeness score. `disclosed_category_count` is the number of distinct data categories or individually-named elements the text discloses. `disclosed_purpose_count` is the number of processing purposes the text discloses. `disclosed_third_party_count` is the number of third-party recipients the text acknowledges, and `named_third_party_count` is how many of those recipients it names individually; the latter may never exceed the former, and a body that breaks that relation is a malformed request. All four must be zero or greater.

A version is created in `DRAFT` with `completeness_score` at 0.0, `gap_count` at 0, `effective_to` null, `published_by_user_id` null, and `authored_by_user_id` stamped with the drafting officer's `X-User-ID`. Creation increments the product's `version` by one.

Submitting the draft for review moves it `DRAFT → IN_REVIEW` and is admitted only when the referenced applicability assessment currently has `state` `APPROVED`; drafting against an assessment that has not cleared review, or that has since been superseded, is refused with `ERR_ASSESSMENT_NOT_APPROVED`. Submission is the moment the completeness score is computed.

The scoring runs in four steps. **Step one** fixes two denominators. The category denominator is the product's current `regulated_element_count` when the version's `specificity_mode` is `ELEMENT_LEVEL`, and is the fixed statutory count of six categories when the `specificity_mode` is `CATEGORY_LEVEL`. The purpose denominator is the number of processing purposes declared on the same product. **Step two** forms three components, each an exact fraction capped at one and — this matters — never rounded at this stage. The category component is one when its denominator is zero, and otherwise the lesser of one and `disclosed_category_count` divided by the category denominator. The purpose component is one when the purpose denominator is zero, and otherwise the lesser of one and `disclosed_purpose_count` divided by the purpose denominator. The third-party component is one when `disclosed_third_party_count` is zero, and otherwise the lesser of one and `named_third_party_count` divided by `disclosed_third_party_count`. **Step three** sets `gap_count` to the number of those three components that are strictly less than one. **Step four** takes the category component weighted at forty per cent, the purpose component weighted at thirty-five per cent, and the third-party component weighted at twenty-five per cent, sums the three weighted values, multiplies by one hundred, and rounds that single result half-up to one decimal place. There is exactly one rounding step, and it comes after the weighting.

The two `specificity_mode` variants are genuinely different regimes rather than presentational choices. Under `ELEMENT_LEVEL`, the category denominator is the product's `regulated_element_count`, so the policy must name every regulated element individually to reach a full category component. Under `CATEGORY_LEVEL`, the denominator is the fixed six statutory categories, so an identical `disclosed_category_count` produces a different score than it would under `ELEMENT_LEVEL` whenever the product's `regulated_element_count` differs from six.

A `ComplianceApprover` may push a version under review back to the author, moving it `IN_REVIEW → DRAFT` with a `return_reason` in the body — a mandatory field that the version does not persist, a privacy policy version carrying no `return_reason` property of its own; doing so resets `completeness_score` to 0.0 and `gap_count` to 0, so a resubmission always rescores against the inventory as it stands at that later moment. This `DRAFT → IN_REVIEW → DRAFT` loop is unbounded.

Publication, reserved to a `ComplianceApprover` and admitted only from `IN_REVIEW`, is the most heavily gated transition in the policy lifecycle. Four conditions apply beyond the state check. The publisher's `X-User-ID` must differ from the recorded `authored_by_user_id`. The version's `completeness_score` must be at least 90.0, and a lower score is refused with `ERR_POLICY_COMPLETENESS_BELOW_THRESHOLD`. The version's `effective_from` must not be earlier than the logical clock's date — publishing a policy that took effect in the past is refused with `ERR_EFFECTIVE_DATE_IN_PAST`, while a date exactly equal to today is admitted. Finally, `effective_from` must not fall inside the effectivity window of any other policy version on the same product whose `state` is `PUBLISHED`, `SUPERSEDED_PENDING_UPDATE`, or `SUPERSEDED`. Each such window runs from that version's `effective_from` inclusive up to its `effective_to` exclusive; a `PUBLISHED` or `SUPERSEDED_PENDING_UPDATE` version has no `effective_to` yet, so its window is treated as running forward without bound. Because the upper bound is exclusive, a new `effective_from` falling exactly on a `SUPERSEDED` version's `effective_to` is admitted — the incumbent stopped being effective on that instant — whereas a date strictly inside any window is refused with `ERR_POLICY_WINDOW_OVERLAP`.

A successful publication moves the version `IN_REVIEW → PUBLISHED`, stamps `published_by_user_id` with the publisher's `X-User-ID`, moves every policy version on the same product whose `state` is `PUBLISHED` or `SUPERSEDED_PENDING_UPDATE` to `SUPERSEDED` with its `effective_to` set to the newly published version's `effective_from`, and sets the product's `policy_compliance_state` to `CURRENT`. That last effect is what cures a lapse: a product knocked to `LAPSED` by the vendor-termination cascade returns to `CURRENT` the moment a replacement policy is published, and the mappings and campaigns that were blocked become activatable again.

Two system-driven transitions complete the picture. A `PUBLISHED` version is moved to `SUPERSEDED_PENDING_UPDATE` when the vendor-termination cascade of §3.4 suspends an `ACTIVE` mapping on the product, and that departure from `PUBLISHED` is precisely what sets the product's `policy_compliance_state` to `LAPSED`. Separately, when a later version is published, an incumbent in `PUBLISHED` is moved `PUBLISHED → SUPERSEDED` and an incumbent in `SUPERSEDED_PENDING_UPDATE` is moved `SUPERSEDED_PENDING_UPDATE → SUPERSEDED`; in both cases `effective_to` is set to the newly published version's `effective_from`. `SUPERSEDED` is the terminal state, and `effective_to` remains null in every other state.

### 3.7. Consumer Rights: Verification, Deadlines, and Downstream Deletion

A `Consumer` files a **rights request** naming its own `consumer_id`, the right being exercised in `request_kind` (`ACCESS`, `DELETE`, or `CONFIRM`), and the intake channel the request arrived on in `submitted_channel` (`IN_APP`, `EMAIL`, or `WEB_FORM`). Filing stamps `received_at` from the logical clock, creates the request in `RECEIVED` with `verification_rounds_used` at zero, `extension_granted` false, `outstanding_task_count` at zero, and `verification_window_ends_at`, `verified_at` and `denial_reason` all null, and computes the governing `response_deadline_at`.

The deadline computation runs on filing, again on successful verification, and again whenever the extension is taken. It starts from a base deadline of forty-five days after `received_at`. If `extension_granted` is true, the extended deadline is a further forty-five days beyond the base — the single permitted extension doubles the response window to ninety days from receipt — and otherwise the extended deadline is simply the base. The governing `response_deadline_at` is then whichever is earlier of two candidates, depending on the `request_kind`. For a `DELETE` request whose `verified_at` is not null, it is the earlier of the extended deadline and thirty days after `verified_at`, because deletion must complete promptly once identity is settled regardless of the outer window. For a `CONFIRM` request, it is the earlier of the extended deadline and thirty days after `received_at`, so a mere confirmation of processing is always due within thirty days of receipt no matter what extension was taken. In every other case — an `ACCESS` request, or a `DELETE` request not yet verified — the governing deadline is the extended deadline itself.

A `PrivacyOfficer` may take the extension exactly once, which sets `extension_granted` to true and recomputes `response_deadline_at`. A second attempt is refused with `ERR_EXTENSION_ALREADY_GRANTED`. Taking the extension is the one action on a rights request that carries no from-state condition at all — the sole exception to §2.7's check 8 — so it is admitted from `RECEIVED`, `VERIFICATION_PENDING`, `VERIFIED` and even the terminal `FULFILLED` and `DENIED`, and the already-granted refusal is the only one it ever raises.

Identity verification has two paths. When the officer needs more from the requester, asking for additional identity information moves the request `RECEIVED → VERIFICATION_PENDING`, increments `verification_rounds_used` by one, and sets `verification_window_ends_at` to ten days after the logical clock. The consumer answers by resubmitting identity information, which moves the request `VERIFICATION_PENDING → RECEIVED` and clears `verification_window_ends_at` back to null; it is admitted only while the logical clock is not later than `verification_window_ends_at`, and a late answer is refused with `ERR_VERIFICATION_WINDOW_EXPIRED`. This `RECEIVED → VERIFICATION_PENDING → RECEIVED` loop is bounded at three rounds: asking again is admitted only while `verification_rounds_used` is strictly below three, and the fourth ask is refused with `ERR_VERIFICATION_ROUNDS_EXHAUSTED`. `verification_window_ends_at` is null in every state other than `VERIFICATION_PENDING`.

The other path settles identity outright. A `PrivacyOfficer` verifies the request from `RECEIVED` by submitting a `verification_token`, which must equal the token minted for that consumer at registration; a mismatch is refused with `ERR_VERIFICATION_TOKEN_MISMATCH`. Successful verification moves the request `RECEIVED → VERIFIED`, stamps `verified_at` with the logical clock, and recomputes `response_deadline_at` — which for a `DELETE` request is where the thirty-day fulfilment clock first bites.

For a `DELETE` request, verification also fans out the downstream deletion obligations. The fan-out selects vendors in four steps. **Step one** takes the distinct `vendor_id` values over the element-purpose mappings that satisfy all of the following at once: `status` is `ACTIVE`; `regulated_flag` is true; `vendor_id` is non-null; the referenced processing purpose's `activity_kind` is `SHARE` or `SELL`; the referenced data element belongs to the same app product as the requesting consumer; and the referenced vendor's `agreement_state` is `EXECUTED`. Those vendors sit at `hop_distance` zero — they received the data directly. **Step two** expands along the flow-down chain: for each already-selected vendor at a hop distance below three whose own `flow_down_clause` is true, every vendor whose `subprocessor_of_id` names it and whose `agreement_state` is `EXECUTED` is added at one hop further out. The expansion repeats until no new vendor is added or the hop distance reaches three, which is the deepest the flow-down obligation reaches. A vendor whose contract carries no flow-down clause terminates the chain at itself: its own subprocessors are not reached. **Step three** dedupes — a vendor reachable at several hop distances is kept once, at the smallest hop distance found. **Step four** creates one **deletion task** per selected vendor, in ascending `hop_distance` and, within a hop distance, in ascending vendor `created_at` — never by identifier — each recording its `consumer_request_id`, its `vendor_id`, its `hop_distance`, `state` `PENDING`, `attempt_count` zero, and null `due_at`, `confirmed_at` and `failure_reason`. The request's `outstanding_task_count` is then recomputed as the number of its tasks whose `state` is `PENDING`, `NOTIFIED` or `FAILED`. **Step five** covers the empty case: when step one selects no vendor at all, no deletion task is created, `outstanding_task_count` stays at zero, and the request moves `VERIFIED → FULFILLED` inside the very same verification call, running fulfilment's own cascade described below. Deletion tasks are created only by this fan-out and are discoverable only through the deletion-task reads.

Working a deletion task is the `PrivacyOfficer`'s job. Notifying a task moves it `PENDING → NOTIFIED`, increments `attempt_count` by one, and sets `due_at` to the logical clock plus that vendor's `deletion_sla_days` days — so a vendor with a thirty-day SLA is due a month out while one with a seven-day SLA is due within the week. Notification requires the vendor's `agreement_state` to be `EXECUTED`, failing which the refusal is `ERR_VENDOR_AGREEMENT_NOT_EXECUTED`, and is admitted only while `attempt_count` is strictly below two. Recording the vendor's confirmation moves the task `NOTIFIED → CONFIRMED` and stamps `confirmed_at` with the logical clock; its first cascade hop recomputes the parent request's `outstanding_task_count`, and its second hop, because that count has reached zero, moves the parent request `VERIFIED → FULFILLED` and runs the request's own fulfilment hops. `CONFIRMED` is the task's terminal state. Recording a failure moves the task `NOTIFIED → FAILED`, records the supplied `failure_reason`, and recomputes the parent request's `outstanding_task_count`. Reissuing a failed instruction moves the task `FAILED → NOTIFIED`, increments `attempt_count` by one, clears `failure_reason` to null, and resets `due_at` to the logical clock plus the vendor's `deletion_sla_days` days; reissue requires the vendor's `agreement_state` to still be `EXECUTED` and is admitted only while `attempt_count` is strictly below two. This `NOTIFIED → FAILED → NOTIFIED` loop is therefore bounded at two attempts in total, and an attempt beyond that — on notify or on reissue alike — is refused with `ERR_TASK_ATTEMPT_LIMIT`.

Fulfilment of the parent request, whether driven explicitly by the officer or by the last task's confirmation, is admitted only from `VERIFIED`, only when `outstanding_task_count` is zero — otherwise `ERR_DELETION_TASKS_OUTSTANDING` — and only while the logical clock is not later than `response_deadline_at`, a late fulfilment being refused with `ERR_RESPONSE_DEADLINE_PASSED`. For a `DELETE` request, fulfilment cascades into consent: its third hop takes the consumer's consent record whose `record_state` is `ACTIVE` and withdraws every granted axis on it — `collection_state` becomes `WITHDRAWN` if it was `GRANTED`, `sharing_state` becomes `WITHDRAWN` if it was `GRANTED`, and `sale_state` becomes `REVOKED` if it was `AUTHORIZED` — setting `last_withdrawn_axis` to `COLLECT`, `last_withdrawn_at` to the logical clock, and `processing_halt_deadline_at` to fifteen days after that, and recomputes the consumer's `deletion_completed_count`. Its fourth hop, because that record's `sharing_state` left `GRANTED`, decrements the product's `active_share_consent_count` by one.

Denial is the other terminal outcome and is reachable from three states. Denying from `RECEIVED` moves the request `RECEIVED → DENIED` and records the supplied `denial_reason`. Denying from `VERIFICATION_PENDING` moves it `VERIFICATION_PENDING → DENIED`, records `denial_reason`, and additionally clears `verification_window_ends_at` to null. Denying from `VERIFIED` moves it `VERIFIED → DENIED`, records `denial_reason`, and additionally moves every deletion task on the request whose `state` is `PENDING`, `NOTIFIED` or `FAILED` into `FAILED` — a `PENDING → FAILED` move for the untouched ones and a `NOTIFIED → FAILED` move for the outstanding ones — with `failure_reason` set to `REQUEST_DENIED` in each case, recomputing `outstanding_task_count` as it goes. Both `FULFILLED` and `DENIED` are terminal.

### 3.8. Geofencing Around Health Facilities

Where the law forbids it, a product may not draw a virtual perimeter around a health facility to collect or infer health data from the people inside. A `PlatformAdmin` registers each such facility as a **geofence zone** against its `app_product_id`, with a label in `zone_name`, the two-letter code of the state the facility sits in in `state_code`, the facility's sensitivity class in `facility_kind` (`SENSITIVE_HEALTH`, `GENERAL_HEALTH`, or `NON_HEALTH`), an operator-facing label for the centre point in `center_label`, and the zone's radius in whole metres in `radius_meters`, which must be between 1 and 5000 inclusive.

Registration derives the zone's `prohibition_rule` from the interaction of state law with the facility class. Two of the five supported jurisdictions — Washington and Nevada — prohibit health-facility geofencing outright; two — Connecticut and California — prohibit it only around sensitive facilities; and Texas permits it. Applying that to the facility class: in a jurisdiction with an outright prohibition, a `SENSITIVE_HEALTH` or `GENERAL_HEALTH` facility yields `prohibition_rule` `PROHIBITED_ALL`, while a `NON_HEALTH` facility yields `PERMITTED`. In a jurisdiction that prohibits only around sensitive facilities, a `SENSITIVE_HEALTH` facility yields `PROHIBITED_ALL`, a `GENERAL_HEALTH` facility yields `PROHIBITED_SENSITIVE_ONLY`, and a `NON_HEALTH` facility yields `PERMITTED`. In a permitting jurisdiction, every facility class yields `PERMITTED`. From the rule follows `min_standoff_meters`: a zone whose `prohibition_rule` is `PROHIBITED_SENSITIVE_ONLY` demands a clearance of five hundred metres; a `PERMITTED` zone demands none, so the value is zero; and for a `PROHIBITED_ALL` zone the field is not applicable because no campaign may ever run against it, so it too is stored and reported as zero. `last_campaign_activated_at` starts null.

A `DataSteward` plans a **geofence campaign** against a zone by naming the `geofence_zone_id`, the `processing_purpose_id` the campaign processes location data for, a `campaign_name`, its own targeting radius in `target_radius_meters` (between 1 and 5000 inclusive), the surveyed distance in metres from the campaign centre to the zone centre in `distance_to_zone_center_meters` (zero or greater), and the inclusive bounds of the interval during which it will occupy the zone in `window_start_at` and `window_end_at`. The end must be strictly later than the start; an inverted or zero-length window is refused with `ERR_WINDOW_END_BEFORE_START`. The campaign is created in `PLANNED` with a null `pause_reason`.

Creation also computes the campaign's `standoff_meters`: the surveyed centre-to-centre distance, less the campaign's own `target_radius_meters`, less the zone's `radius_meters`. It is the clearance between the two circles, and it is deliberately not clamped — two overlapping circles produce a zero or negative standoff, which is exactly the signal the activation gate needs.

Activation, which moves a campaign `PLANNED → ACTIVE` or resumes it `PAUSED → ACTIVE`, is where the geofencing restrictions bite. Two checks apply on both paths. The zone's `prohibition_rule` must not be `PROHIBITED_ALL`, and an attempt against such a zone is refused with `ERR_GEOFENCE_PROHIBITED`. The campaign's `standoff_meters` must be at least the zone's `min_standoff_meters` — a standoff exactly equal to the minimum is admitted, and anything strictly below it is refused with `ERR_GEOFENCE_STANDOFF_VIOLATION`. The product's `policy_compliance_state` must also not be `LAPSED` on either path, on pain of `ERR_POLICY_LAPSED`.

Activation from `PLANNED` adds two further checks that a resume from `PAUSED` does not repeat. First, exclusivity on the zone: the campaign's own closed interval from `window_start_at` to `window_end_at` inclusive must share no instant with the closed interval of any other campaign on the same zone whose `state` is `PLANNED`, `ACTIVE`, or `PAUSED`. Because both intervals are closed, merely touching endpoints collide, and the conflict is refused with `ERR_CAMPAIGN_WINDOW_CONFLICT`. Second, a cooldown: the zone's `last_campaign_activated_at` must be null, or the elapsed logical-clock time since it must be at least twenty-four hours; an activation strictly inside that day-long cooldown is refused with `ERR_ZONE_COOLDOWN_ACTIVE`. Neither the window-exclusivity test nor the cooldown is re-evaluated when a paused campaign resumes.

Every successful activation, from `PLANNED` or from `PAUSED`, sets the zone's `last_campaign_activated_at` to the logical clock; a resume additionally clears `pause_reason` back to null. Pausing an `ACTIVE` campaign moves it `ACTIVE → PAUSED` and records the operator's `pause_reason` from the body — or sets it to `POLICY_LAPSED` when the pause was driven by the fifth hop of the vendor-termination cascade rather than by an operator. A campaign may cycle `ACTIVE → PAUSED → ACTIVE` freely. Ending a campaign is admitted from all three non-terminal states and takes it to the terminal `ENDED`: `PLANNED → ENDED` for one never activated, `ACTIVE → ENDED` for one running, and `PAUSED → ENDED` for one suspended. Ending releases the campaign's window on the zone, so that another campaign may thereafter occupy an interval that previously collided with it.

### 3.9. Breach Reportability and the Security Risk Program

When data escapes, a `SecurityEngineer` records a **breach incident** against the affected `app_product_id`, with an operator-facing `incident_label`, the instant of discovery in `discovered_at`, the categories of data involved in `breach_scope` (`CHD_ONLY`, `GENERAL_PII_ONLY`, or `MIXED`), whether the exposed data had been rendered unusable in `protection_state` (`UNPROTECTED` or `ENCRYPTED_SECURED`), the total number of people exposed in `affected_consumer_count`, which must be zero or greater, and the largest number of affected people resident in any single state in `affected_state_max_count`, which may be no greater than the total — a body breaking that relation is the malformed request described in check 4 of §2.7. The incident is created in `DISCOVERED` with `health_rule_deadline_at`, `general_rule_deadline_at`, `governing_deadline_at` and `notified_at` all null, `media_notice_required` and `media_notice_sent` both false, and `exposure_contribution_cents` at zero.

Assessment forks on the protection state, and the two branches have deliberately divergent effects. When `protection_state` is `ENCRYPTED_SECURED`, the encryption safe harbour applies: the incident moves `DISCOVERED → NOT_REPORTABLE`, all three deadline fields stay null, `media_notice_required` stays false, `exposure_contribution_cents` stays at zero, and the product's `exposure_cents` is therefore unchanged. `NOT_REPORTABLE` is terminal. When `protection_state` is `UNPROTECTED`, the incident moves `DISCOVERED → REPORTABLE` and the full deadline analysis runs.

That analysis asks which of two notification regimes applies, and it can be both at once. The health-specific rule applies when the `breach_scope` is `CHD_ONLY` or `MIXED`; the general breach rule applies when the `breach_scope` is `GENERAL_PII_ONLY` or `MIXED`. Where the health-specific rule applies, `health_rule_deadline_at` is sixty days after `discovered_at`, and otherwise it is null. Where the general rule applies, `general_rule_deadline_at` is thirty days after `discovered_at`, and otherwise it is null. The `governing_deadline_at` is then whichever of the non-null values is earlier. The practical consequence deserves emphasis: a `CHD_ONLY` breach is governed by the sixty-day health deadline; a `GENERAL_PII_ONLY` breach by the thirty-day general deadline; and a `MIXED` breach by the thirty-day general deadline, which overrides the co-applicable sixty-day health deadline even though both are recorded. `governing_deadline_at` is null only on the `NOT_REPORTABLE` branch.

Two further values are set on the reportable branch. `media_notice_required` becomes true when `affected_state_max_count` is at least five hundred — a concentration that large in one state triggers substitute media notice — and false otherwise. And `exposure_contribution_cents` becomes `affected_consumer_count` multiplied by twelve dollars per exposed consumer, which is 1200 cents each; that amount is added to the product's `exposure_cents` by exactly that much.

Notification, admitted only from `REPORTABLE`, moves the incident `REPORTABLE → NOTIFIED`, stamps `notified_at` with the logical clock, and records `media_notice_sent` from the request body, where it is a mandatory boolean. It is admitted only while the logical clock is not later than `governing_deadline_at`, a late notification being refused with `ERR_NOTIFICATION_DEADLINE_PASSED`. And when `media_notice_required` is true, the body must set `media_notice_sent` to true; a notification that omits the required media accompaniment is refused with `ERR_MEDIA_NOTICE_REQUIRED`. Where `media_notice_required` is false, either value of `media_notice_sent` is accepted. `NOTIFIED` is terminal.

An engineer who concludes on further investigation that the incident was not reportable after all may retract the finding, moving it `REPORTABLE → DISCOVERED`. Retraction compensates the assessment exactly: it clears `health_rule_deadline_at`, `general_rule_deadline_at` and `governing_deadline_at` back to null, resets `media_notice_required` to false, subtracts the incident's previous `exposure_contribution_cents` from the product's `exposure_cents`, and resets `exposure_contribution_cents` to zero. Because the subtraction is exactly the amount the assessment added, a `DISCOVERED → REPORTABLE → DISCOVERED` round trip leaves the product's `exposure_cents` exactly where it started.

The security program runs on its own artefact. A `SecurityEngineer` documents a **security risk assessment** against the `app_product_id` with an `assessment_label`, four safeguard maturity scores each between 0 and 100 inclusive — `admin_control_score`, `technical_control_score`, `physical_control_score`, and `vendor_oversight_score` — the number of documented control gaps in `documented_gap_count` (zero or greater), and whether a written remediation plan accompanies the documentation in `remediation_plan_present`, which defaults to false. It is created in `DRAFT` with a null `finalized_at`, and the same six inputs remain revisable while it is still in `DRAFT`.

Residual risk is scored on creation, on every revision, and again on finalisation, and the rounding order is pinned: weight first, sum the unrounded weighted terms, and round once at the end. Rounding each weighted domain term to two decimals before summing produces a different score for some inputs and is wrong. **Step one** computes a penalty multiplier as one plus three and a half per cent per documented gap — that is, one plus 0.035 multiplied by `documented_gap_count` — capped at 2.00, so that once `documented_gap_count` reaches twenty-nine the multiplier is pinned at exactly 2.00 and further gaps no longer raise it. **Step two** computes each domain's raw gap as one hundred less that domain's maturity score, taken in the fixed order administrative, technical, physical, vendor. **Step three** multiplies each raw gap by the penalty multiplier and by that domain's weight — thirty per cent for administrative, thirty-five per cent for technical, ten per cent for physical, twenty-five per cent for vendor oversight — and does not round the result. **Step four** sums those four weighted terms and rounds the single total half-up to two decimal places, giving `residual_risk_score`. **Step five** bands the score into `risk_tier`: strictly below 20 is `LOW`; from 20 up to but not including 40 is `MODERATE`; from 40 up to but not including 60 is `HIGH`; and 60 or above is `CRITICAL`. Nothing outside this one assessment row feeds the computation.

Finalisation moves the assessment `DRAFT → FINALIZED` and stamps `finalized_at` with the logical clock. Two conditions gate it. The product must have an applicability assessment currently in `APPROVED` — there is no point documenting a security program for a product whose regulatory track is unsettled, and the attempt is refused with `ERR_ASSESSMENT_NOT_APPROVED`. And a `risk_tier` of `HIGH` or `CRITICAL` may be finalised only when `remediation_plan_present` is true; a high-risk posture with no written plan is refused with `ERR_REMEDIATION_PLAN_REQUIRED`, whereas a `LOW` or `MODERATE` tier finalises with or without a plan. Finalisation then refreshes the product's `security_program_state` from this assessment's `risk_tier`, per §2.11. `FINALIZED` is terminal.

## 4. Endpoint Definitions

Operations that bring a new resource into existence return `201 Created`. Operations that modify an existing resource — including every state transition, every amendment, and the logical-clock control — return `200 OK`. Reads return `200 OK`. Errors carry the status codes catalogued in §5.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the server's logical clock to an explicit UTC instant | PlatformAdmin |
| POST | `/health-data/app-products` | Register a consumer health application product | PlatformAdmin |
| GET | `/health-data/app-products` | List app products | PlatformAdmin, PrivacyOfficer, ComplianceApprover, DataSteward, SecurityEngineer |
| GET | `/health-data/app-products/{id}` | Read one app product with its derived compliance counters | PlatformAdmin, PrivacyOfficer, ComplianceApprover, DataSteward, SecurityEngineer |
| PATCH | `/health-data/app-products/{id}` | Update the product's size and HIPAA-ratio inputs | PlatformAdmin |
| GET | `/health-data/app-products/{id}/compliance-summary` | Computed read of the product's whole compliance posture | PlatformAdmin, PrivacyOfficer, ComplianceApprover, DataSteward, SecurityEngineer |
| POST | `/health-data/applicability-assessments` | Create a DRAFT applicability assessment for a product | PrivacyOfficer |
| GET | `/health-data/applicability-assessments` | List applicability assessments | PlatformAdmin, PrivacyOfficer, ComplianceApprover, DataSteward, SecurityEngineer |
| GET | `/health-data/applicability-assessments/{id}` | Read one applicability assessment | PlatformAdmin, PrivacyOfficer, ComplianceApprover, DataSteward, SecurityEngineer |
| POST | `/health-data/applicability-assessments/{id}/submit` | Submit the assessment and run the applicability determination | PrivacyOfficer |
| POST | `/health-data/applicability-assessments/{id}/approve` | Approve the assessment and pin the product's regulatory track | ComplianceApprover |
| POST | `/health-data/applicability-assessments/{id}/return` | Return the assessment to the privacy officer with a reason | ComplianceApprover |
| POST | `/health-data/applicability-assessments/{id}/revise` | Reopen a returned assessment for revision | PrivacyOfficer |
| POST | `/health-data/data-elements` | Declare a collected data element and classify it | DataSteward |
| GET | `/health-data/data-elements` | List data elements | PlatformAdmin, PrivacyOfficer, ComplianceApprover, DataSteward, SecurityEngineer |
| GET | `/health-data/data-elements/{id}` | Read one data element with its classification | PlatformAdmin, PrivacyOfficer, ComplianceApprover, DataSteward, SecurityEngineer |
| PATCH | `/health-data/data-elements/{id}` | Edit a data element's descriptive and classification inputs | DataSteward |
| POST | `/health-data/data-elements/{id}/retire` | Retire a data element and cascade to derived elements and mappings | DataSteward |
| POST | `/health-data/data-elements/{id}/reinstate` | Reinstate a retired data element | DataSteward |
| POST | `/health-data/processing-purposes` | Declare a processing purpose and its consent axis | DataSteward |
| GET | `/health-data/processing-purposes` | List processing purposes | PlatformAdmin, PrivacyOfficer, ComplianceApprover, DataSteward, SecurityEngineer |
| GET | `/health-data/processing-purposes/{id}` | Read one processing purpose | PlatformAdmin, PrivacyOfficer, ComplianceApprover, DataSteward, SecurityEngineer |
| POST | `/health-data/element-purpose-mappings` | Propose a mapping of one data element to one processing purpose | DataSteward |
| GET | `/health-data/element-purpose-mappings` | List element-purpose mappings | PlatformAdmin, PrivacyOfficer, ComplianceApprover, DataSteward, SecurityEngineer |
| GET | `/health-data/element-purpose-mappings/{id}` | Read one element-purpose mapping | PlatformAdmin, PrivacyOfficer, ComplianceApprover, DataSteward, SecurityEngineer |
| POST | `/health-data/element-purpose-mappings/{id}/activate` | Activate a proposed or suspended mapping | DataSteward |
| POST | `/health-data/element-purpose-mappings/{id}/suspend` | Suspend an active mapping | DataSteward |
| POST | `/health-data/element-purpose-mappings/{id}/retire` | Retire a mapping permanently | DataSteward |
| POST | `/health-data/consumers` | Register a consumer and issue a verification token | PlatformAdmin |
| GET | `/health-data/consumers` | List consumers | PlatformAdmin, PrivacyOfficer, ComplianceApprover, DataSteward, SecurityEngineer |
| GET | `/health-data/consumers/{id}` | Read one consumer | PlatformAdmin, PrivacyOfficer, ComplianceApprover, DataSteward, SecurityEngineer, Consumer |
| POST | `/health-data/consent-records` | Open a new consent record, superseding the incumbent | PrivacyOfficer, PlatformAdmin |
| GET | `/health-data/consent-records` | List consent records | PlatformAdmin, PrivacyOfficer, ComplianceApprover, DataSteward, SecurityEngineer, Consumer |
| GET | `/health-data/consent-records/{id}` | Read one consent record with all three axes | PlatformAdmin, PrivacyOfficer, ComplianceApprover, DataSteward, SecurityEngineer, Consumer |
| POST | `/health-data/consent-records/{id}/grants` | Grant consent on exactly one axis of the record | Consumer |
| POST | `/health-data/consent-records/{id}/withdrawals` | Withdraw consent on one axis, cascading to dependent axes | Consumer |
| POST | `/health-data/privacy-policy-versions` | Draft a privacy policy version against an approved assessment | PrivacyOfficer |
| GET | `/health-data/privacy-policy-versions` | List privacy policy versions | PlatformAdmin, PrivacyOfficer, ComplianceApprover, DataSteward, SecurityEngineer |
| GET | `/health-data/privacy-policy-versions/{id}` | Read one privacy policy version | PlatformAdmin, PrivacyOfficer, ComplianceApprover, DataSteward, SecurityEngineer |
| POST | `/health-data/privacy-policy-versions/{id}/submit-review` | Submit the draft for review and score its completeness | PrivacyOfficer |
| POST | `/health-data/privacy-policy-versions/{id}/return-to-draft` | Return a policy under review to draft | ComplianceApprover |
| POST | `/health-data/privacy-policy-versions/{id}/publish` | Publish the policy version, superseding the incumbent | ComplianceApprover |
| POST | `/health-data/consumer-requests` | File a consumer rights request | Consumer |
| GET | `/health-data/consumer-requests` | List consumer rights requests | PlatformAdmin, PrivacyOfficer, ComplianceApprover, DataSteward, SecurityEngineer, Consumer |
| GET | `/health-data/consumer-requests/{id}` | Read one consumer rights request | PlatformAdmin, PrivacyOfficer, ComplianceApprover, DataSteward, SecurityEngineer, Consumer |
| POST | `/health-data/consumer-requests/{id}/request-more-info` | Ask the consumer for additional identity information | PrivacyOfficer |
| POST | `/health-data/consumer-requests/{id}/resubmit-identity` | Supply additional identity information inside the open window | Consumer |
| POST | `/health-data/consumer-requests/{id}/verify` | Verify identity and fan out deletion tasks for DELETE requests | PrivacyOfficer |
| POST | `/health-data/consumer-requests/{id}/extend` | Take the single permitted response-deadline extension | PrivacyOfficer |
| POST | `/health-data/consumer-requests/{id}/fulfill` | Record fulfillment of a verified request | PrivacyOfficer |
| POST | `/health-data/consumer-requests/{id}/deny` | Deny a request with a reason | PrivacyOfficer |
| GET | `/health-data/deletion-tasks` | List deletion tasks | PlatformAdmin, PrivacyOfficer, ComplianceApprover, DataSteward, SecurityEngineer |
| GET | `/health-data/deletion-tasks/{id}` | Read one downstream deletion task | PlatformAdmin, PrivacyOfficer, ComplianceApprover, DataSteward, SecurityEngineer |
| POST | `/health-data/deletion-tasks/{id}/notify` | Send the deletion instruction to the vendor | PrivacyOfficer |
| POST | `/health-data/deletion-tasks/{id}/confirm` | Record the vendor's deletion confirmation | PrivacyOfficer |
| POST | `/health-data/deletion-tasks/{id}/fail` | Record a failed deletion instruction | PrivacyOfficer |
| POST | `/health-data/deletion-tasks/{id}/reissue` | Reissue a failed deletion instruction | PrivacyOfficer |
| POST | `/health-data/vendors` | Register a vendor or subprocessor with its contract clauses | PrivacyOfficer |
| GET | `/health-data/vendors` | List vendors | PlatformAdmin, PrivacyOfficer, ComplianceApprover, DataSteward, SecurityEngineer |
| GET | `/health-data/vendors/{id}` | Read one vendor with its agreement posture | PlatformAdmin, PrivacyOfficer, ComplianceApprover, DataSteward, SecurityEngineer |
| PATCH | `/health-data/vendors/{id}` | Amend the vendor's contract clauses while the agreement is DRAFT | PrivacyOfficer |
| POST | `/health-data/vendors/{id}/execute-agreement` | Execute the vendor agreement | PrivacyOfficer |
| POST | `/health-data/vendors/{id}/terminate-agreement` | Terminate the agreement and run the five-hop compliance cascade | PrivacyOfficer |
| POST | `/health-data/geofence-zones` | Register a health facility zone and derive its prohibition rule | PlatformAdmin |
| GET | `/health-data/geofence-zones` | List geofence zones | PlatformAdmin, PrivacyOfficer, ComplianceApprover, DataSteward, SecurityEngineer |
| GET | `/health-data/geofence-zones/{id}` | Read one geofence zone | PlatformAdmin, PrivacyOfficer, ComplianceApprover, DataSteward, SecurityEngineer |
| POST | `/health-data/geofence-campaigns` | Plan a location campaign near a zone and compute its standoff | DataSteward |
| GET | `/health-data/geofence-campaigns` | List geofence campaigns | PlatformAdmin, PrivacyOfficer, ComplianceApprover, DataSteward, SecurityEngineer |
| GET | `/health-data/geofence-campaigns/{id}` | Read one geofence campaign | PlatformAdmin, PrivacyOfficer, ComplianceApprover, DataSteward, SecurityEngineer |
| POST | `/health-data/geofence-campaigns/{id}/activate` | Activate a planned or paused campaign | DataSteward |
| POST | `/health-data/geofence-campaigns/{id}/pause` | Pause an active campaign | DataSteward |
| POST | `/health-data/geofence-campaigns/{id}/end` | End a campaign and release its window on the zone | DataSteward |
| POST | `/health-data/breach-incidents` | Record a discovered breach | SecurityEngineer |
| GET | `/health-data/breach-incidents` | List breach incidents | PlatformAdmin, PrivacyOfficer, ComplianceApprover, DataSteward, SecurityEngineer |
| GET | `/health-data/breach-incidents/{id}` | Read one breach incident with both rule deadlines | PlatformAdmin, PrivacyOfficer, ComplianceApprover, DataSteward, SecurityEngineer |
| POST | `/health-data/breach-incidents/{id}/assess` | Assess reportability under the health-specific and general rules | SecurityEngineer |
| POST | `/health-data/breach-incidents/{id}/notify` | Record notification before the governing deadline | SecurityEngineer |
| POST | `/health-data/breach-incidents/{id}/retract` | Retract a reportability finding and compensate its exposure | SecurityEngineer |
| POST | `/health-data/security-risk-assessments` | Document a security risk assessment and score residual risk | SecurityEngineer |
| GET | `/health-data/security-risk-assessments` | List security risk assessments | PlatformAdmin, PrivacyOfficer, ComplianceApprover, DataSteward, SecurityEngineer |
| GET | `/health-data/security-risk-assessments/{id}` | Read one security risk assessment | PlatformAdmin, PrivacyOfficer, ComplianceApprover, DataSteward, SecurityEngineer |
| PATCH | `/health-data/security-risk-assessments/{id}` | Revise the control scores and gap count of a draft assessment | SecurityEngineer |
| POST | `/health-data/security-risk-assessments/{id}/finalize` | Finalize the assessment and refresh the security program state | SecurityEngineer |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_CONSUMER_SCOPE_VIOLATION` | 403 |
| `ERR_APP_PRODUCT_NOT_FOUND` | 404 |
| `ERR_CONSUMER_NOT_FOUND` | 404 |
| `ERR_VENDOR_NOT_FOUND` | 404 |
| `ERR_DATA_ELEMENT_NOT_FOUND` | 404 |
| `ERR_PURPOSE_NOT_FOUND` | 404 |
| `ERR_RESOURCE_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_CROSS_PRODUCT_REFERENCE` | 409 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_ALREADY_TERMINAL` | 409 |
| `ERR_ELEMENT_RETIRED` | 409 |
| `ERR_POLICY_NOT_IN_REVIEW` | 409 |
| `ERR_VENDOR_AGREEMENT_NOT_EXECUTED` | 409 |
| `ERR_STALE_PRODUCT_VERSION` | 412 |
| `ERR_STALE_CONSUMER_VERSION` | 412 |
| `ERR_GEOFENCE_PROHIBITED` | 403 |
| `ERR_GEOFENCE_STANDOFF_VIOLATION` | 422 |
| `ERR_MINOR_SALE_PROHIBITED` | 403 |
| `ERR_CONSENT_BUNDLING_PROHIBITED` | 422 |
| `ERR_COLLECTION_CONSENT_REQUIRED` | 409 |
| `ERR_SHARING_CONSENT_REQUIRED` | 409 |
| `ERR_DUPLICATE_ELEMENT_KEY` | 409 |
| `ERR_DUPLICATE_PURPOSE_KEY` | 409 |
| `ERR_DUPLICATE_CONSUMER_REF` | 409 |
| `ERR_DUPLICATE_VENDOR_NAME` | 409 |
| `ERR_DERIVATION_SOURCE_REQUIRED` | 422 |
| `ERR_INFERENCE_CYCLE` | 422 |
| `ERR_INFERENCE_DEPTH_EXCEEDED` | 422 |
| `ERR_ELEMENT_PARENT_RETIRED` | 409 |
| `ERR_ASSESSMENT_REVISION_LIMIT` | 409 |
| `ERR_VERIFICATION_ROUNDS_EXHAUSTED` | 409 |
| `ERR_TASK_ATTEMPT_LIMIT` | 409 |
| `ERR_EXTENSION_ALREADY_GRANTED` | 409 |
| `ERR_ASSESSMENT_NOT_APPROVED` | 409 |
| `ERR_APPLICABILITY_UNDETERMINED` | 409 |
| `ERR_VENDOR_REQUIRED_FOR_DISCLOSURE` | 422 |
| `ERR_VENDOR_AGREEMENT_DEFICIENT` | 409 |
| `ERR_FLOW_DOWN_CLAUSE_MISSING` | 422 |
| `ERR_AUDIT_RIGHTS_MISSING` | 422 |
| `ERR_SUBPROCESSOR_PARENT_NOT_EXECUTED` | 409 |
| `ERR_POLICY_LAPSED` | 409 |
| `ERR_EFFECTIVE_DATE_IN_PAST` | 422 |
| `ERR_POLICY_WINDOW_OVERLAP` | 409 |
| `ERR_WINDOW_END_BEFORE_START` | 422 |
| `ERR_CAMPAIGN_WINDOW_CONFLICT` | 409 |
| `ERR_ZONE_COOLDOWN_ACTIVE` | 409 |
| `ERR_VERIFICATION_WINDOW_EXPIRED` | 409 |
| `ERR_VERIFICATION_TOKEN_MISMATCH` | 422 |
| `ERR_RESPONSE_DEADLINE_PASSED` | 409 |
| `ERR_DELETION_TASKS_OUTSTANDING` | 409 |
| `ERR_NOTIFICATION_DEADLINE_PASSED` | 409 |
| `ERR_MEDIA_NOTICE_REQUIRED` | 422 |
| `ERR_POLICY_COMPLETENESS_BELOW_THRESHOLD` | 422 |
| `ERR_REMEDIATION_PLAN_REQUIRED` | 422 |
| `ERR_NO_ACTIVE_ELEMENTS` | 409 |
