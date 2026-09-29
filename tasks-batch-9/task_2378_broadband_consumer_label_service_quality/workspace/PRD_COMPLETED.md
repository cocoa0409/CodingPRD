# Broadband Consumer Label Compliance API — Product Requirements Document

## 1. Introduction

Every retail broadband offer that an internet service provider puts in front of a consumer now has to arrive with a standardised nutrition-style label: the access technology, the typical download and upload speeds actually observed on the network, the typical latency, the introductory price and the price that replaces it when the promotion ends, an itemised list of every recurring fee and government tax, the data allowance and the cost of exceeding it, the early termination fee, and a statement of whether the plan participates in the federal low-income discount programme. The label is not marketing copy — it is a regulated disclosure, and every number printed on it must be traceable to evidence the provider can hand to a regulator months later.

This API is the system of record behind that obligation. It carries the measurement chain (a published test methodology, registered probe panels, recorded measurement runs, and typical-speed attestations computed from those runs under one of two documented algorithms), the disclosure chain (versioned labels with an itemised fee block, translations verified for every locale the plan is obliged to serve, accessible renderings, and an archive of every label that was ever displayed), and the accountability chain (consumer complaints alleging speed, latency, reliability or fee shortfalls; investigations that measure the shortfall against the exact figures the disputed label carried; remediation credits; and regulator dockets that must be answered with both a technical evidence packet and a resolution report before the deadline).

The design pressure throughout is that a claim must never outlive its evidence. Withdrawing a single measurement run can knock a plan's evidence pool below the minimum its methodology demands, which revokes the attestation, leaves the published label standing but unsubstantiated, freezes the plan's disclosure posture, and flags every complaint that is still disputing that label. Conversely, correcting a price on a plan does not silently rewrite the label a consumer already saw — it marks the disclosure as drifted and restricts the sales channel until a fresh label is published. The rules below are written so that an engineer can reproduce those consequences exactly, in the order the system evaluates them.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide contracts: authentication, envelope shape, pagination, the logical clock, identity and versioning of records, monetary precision, optimistic concurrency, the plan-level disclosure gate, segregation of duties, and the order in which rejections are decided.

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, declaring the capacity in which that principal acts. A request missing either header, or naming a role that is not one of the seven recognised roles, is rejected with `ERR_UNAUTHENTICATED` (401). A request whose role is recognised but is not authorised for the operation being called is rejected with `ERR_UNAUTHORIZED` (403).

The seven roles are `ComplianceOfficer`, `NetworkEngineer`, `LocalizationSpecialist`, `ComplaintAnalyst`, `RegulatoryLiaison`, `RetailAgent` and `Subscriber`.

A `ComplianceOfficer` owns plan and label governance — plan definition and amendment, fee itemisation, methodology publication, attestation certification, label drafting, publication and withdrawal, and the voiding of remediation credits. A `NetworkEngineer` owns performance measurement — authoring methodology documents, registering probes, recording and invalidating measurement runs, and computing attestations. A `LocalizationSpecialist` owns label translation and its verification. A `ComplaintAnalyst` owns the complaint investigation lifecycle from triage through resolution and reopening. A `RegulatoryLiaison` owns regulator dockets. A `RetailAgent` owns the consumer-facing sales surface — subscriber enrolment, label disclosure, and plan-change or price-increase notices. A `Subscriber` is the consumer.

For the six operator roles — `ComplianceOfficer`, `NetworkEngineer`, `LocalizationSpecialist`, `ComplaintAnalyst`, `RegulatoryLiaison` and `RetailAgent` — `X-User-ID` is an opaque operator identifier that is not tied to any persisted entity. The server records it where a transition declares that it should (as `created_by_user_id` and `published_by_user_id` on a `LabelVersion`, as `created_by_user_id` and `verified_by_user_id` on a `LabelTranslation`, as `disclosed_by_user_id` on a `LabelDisclosure`, and as `issued_by_user_id` and `voided_by_user_id` on a `RemediationCredit`), and it compares it against another recorded operator id for the segregation-of-duties controls in §2.10, but it never compares it to any entity's `id`.

When `X-User-Role` is `Subscriber`, `X-User-ID` is the `id` of the acting `SubscriberAccount`. Ownership checks compare the resource's account reference to `X-User-ID`: a `SubscriberAccount` matches when its own `id` equals `X-User-ID`, and a `Complaint`, a `LabelDisclosure` or a `PlanChangeNotice` matches when its `account_id` equals `X-User-ID`. A `Subscriber` who targets a record belonging to a different account is rejected with `ERR_ACCOUNT_SCOPE_VIOLATION` (403). This scoping applies to eleven operations: reading one account, listing and recording that account's disclosures, filing a complaint, reading one complaint, listing complaints, withdrawing a complaint, listing a complaint's remediation credits, reading one notice, listing notices, and acknowledging a notice. On the two scoped list endpoints — listing complaints and listing notices — the refusal is conditional on the query: a `Subscriber` who supplies an `account_id` filter naming a different account is refused with `ERR_ACCOUNT_SCOPE_VIOLATION`, while a `Subscriber` who supplies no `account_id` filter is silently narrowed to their own account rather than refused, and one who supplies their own id is simply served. A `Subscriber` is not authorised to list subscriber accounts at all, so that attempt is refused with `ERR_UNAUTHORIZED` (403) at ladder step 2 and never reaches the scope check. Listing the disclosures recorded against one label version, by contrast, is authorised for every role and is not account-scoped at all: a `Subscriber` calling it sees every account's disclosure rows for that label.

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

List endpoints are paginated through two query parameters. `limit` caps the number of records returned; it defaults to 10, its minimum accepted value is 1 and its maximum is 100. `offset` is the number of records to skip and defaults to 0; its minimum accepted value is 0. A `limit` outside the range 1 through 100 inclusive, or a negative `offset`, is a malformed request and is rejected with `ERR_INVALID_REQUEST`.

Unless a specific endpoint says otherwise, list results are ordered by `created_at` ascending, with ties — which are common, because every record created while the logical clock is stationary shares a `created_at` — broken by insertion order, so rows always come back in the order they were created. A filter value that cannot be parsed, or that names no member of the underlying enumeration, is not a malformed request: it simply matches no records and the page comes back empty.

Every list response repeats `limit` and `offset` in the envelope's `meta` object alongside `total_count` (the number of records matching the filters before pagination is applied) and `has_more` (true when records matching the filters remain beyond the current page).

### 2.4. The Logical Clock

Nothing in this system reads wall-clock time. Every temporal rule — measurement window admissibility, label display windows, the complaint response deadline, the reopen window, notice periods, pricing phase, and every `*_at` timestamp the server writes — reads a single server-held logical UTC clock. On startup that clock reads exactly `2026-08-01T00:00:00Z`, and it must continue to read that value until it is explicitly repositioned; falling back to real wall-clock time is incorrect.

Any of the seven roles may reposition the clock through an administrative test-driving capability that accepts the target instant as `to_iso8601` and answers with an object carrying `current_utc`. Repositioning the clock mutates no entity: it does not recompute postures, does not advance state machines, and does not backfill timestamps. Subsequent operations simply read the new value.

### 2.5. Record Identity, Versioning and the Disclosure Archive

Every resource in the system carries a server-minted `id` formatted as a UUID with no type prefix, and a `created_at` timestamp in ISO 8601 UTC form with three fractional digits, taken from the logical clock at creation. Client-supplied identifiers are never honoured. The three-fractional-digit rendering applies only to timestamps the server itself writes; an instant supplied by the client in a request body — a measurement window bound, a sample's `observed_at`, a label's `effective_from` or `effective_until`, a `service_start_date`, a `service_observed_date`, an `effective_date` or a `response_due_at` — is stored and echoed back exactly as supplied, with no normalisation of its precision or offset, provided it parses as an ISO 8601 instant (the seconds, the fractional part and an explicit offset are each optional, a space may stand in for the `T`, and an absent offset is read as UTC).

All resources except a `LabelDisclosure` additionally carry `updated_at` — an ISO 8601 UTC timestamp refreshed on every mutation of the record — and `version`, an integer that starts at 1 on creation and increments by one on every mutation, including mutations the server performs on its own initiative when reconciling a derived field. A `LabelDisclosure` is an immutable audit event: it carries only `id` and `created_at`, and both `updated_at` and `version` are absent from it. Conversely, several actions require a free-text justification on the request that the target entity declares no field for — a plan amendment's `change_justification`, a label withdrawal's `reason`, a triage's `priority_note`, a reopen's `reopen_reason`, a complaint withdrawal's `withdraw_reason` and a regulator filing's `summary`. Each is validated as a required non-empty string and is then discarded: it is not persisted anywhere and never appears in any response.

Several derived fields are reconciled across aggregate boundaries, and each such reconciliation is a mutation of the record it lands on. Recording or invalidating a measurement run recomputes `ServicePlan.evidence_sample_total` and increments the plan's `version`. Creating an attestation, drafting a label, publishing a label, withdrawing a label, amending a plan, certifying an attestation that re-substantiates a published label, and upholding a complaint each increment `ServicePlan.version` as well. Adding a translation to a label and verifying a translation each increment `LabelVersion.version`, and verification also increments `LabelVersion.verified_locale_count` by one. Recomputing an account's credit balance increments `SubscriberAccount.version`, as does moving an account into a pending-change posture, as does recording a label disclosure against the account — because that rewrites its `last_disclosed_label_version_id` — and as does effecting a notice on it. Publishing a methodology document increments `MethodologyDocument.version`; certifying an attestation increments `PerformanceAttestation.version`. A server-initiated recomputation that lands on exactly the values the record already held is not a mutation and increments nothing: recomputing a draft label's priced figures after a plan amendment or a new fee line leaves that label's `updated_at` and `version` alone unless at least one computed field actually changed.

Because the label is an archival disclosure, superseded labels are never deleted. A published label that is displaced by a successor becomes archived rather than discarded, and every `LabelDisclosure` recorded against it stays readable: the disclosure retains its own copy of the label's `disclosed_label_version_seq` and `disclosed_net_monthly_cents` precisely so the historical record survives archival. Each account also tracks `last_disclosed_label_version_id`, the label referenced by its most recent disclosure ordered by `created_at` descending, which is null until the account has at least one disclosure and is never client-supplied. Similarly, `ServicePlan.active_label_version_id` names the plan's currently published label — by invariant there is at most one — and is null when the plan has none; it too is maintained by the server alone.

### 2.6. Reference Resolution Order

When a path contains more than one identifier, the identifiers are resolved strictly left to right, and the request fails on the first one that names nothing. Verifying a translation, for example, resolves the label version before the translation, so a request naming a nonexistent label under which a translation is sought answers `ERR_LABEL_VERSION_NOT_FOUND` rather than `ERR_TRANSLATION_NOT_FOUND`. After the path is fully resolved, foreign keys carried in the request body are resolved in the order the body fields are declared for that operation.

Each entity has its own not-found code, all of them 404: `ERR_SERVICE_PLAN_NOT_FOUND` (for a plan named by a path segment or by `plan_id` or `target_plan_id`), `ERR_METHODOLOGY_DOCUMENT_NOT_FOUND`, `ERR_MEASUREMENT_PROBE_NOT_FOUND` (for a `probe_id` that names nothing), `ERR_TEST_RUN_NOT_FOUND`, `ERR_ATTESTATION_NOT_FOUND`, `ERR_LABEL_VERSION_NOT_FOUND` (for a path segment or a `disputed_label_version_id`), `ERR_TRANSLATION_NOT_FOUND`, `ERR_SUBSCRIBER_ACCOUNT_NOT_FOUND` (for a path segment or an `account_id`), `ERR_COMPLAINT_NOT_FOUND` (for a path segment or a `complaint_id`), `ERR_REMEDIATION_CREDIT_NOT_FOUND`, `ERR_REGULATOR_INQUIRY_NOT_FOUND` and `ERR_PLAN_CHANGE_NOTICE_NOT_FOUND`.

### 2.7. Money, Rounding and Percentile Precision

All money in this system is expressed as a whole number of cents in an integer field, and the rounding method wherever rounding is required is round half up. Three families of computation carry pinned precision.

Monetary rounding happens at the individual fee line, never at the phase total. When a percentage-based fee line is itemised, the product of its rate and the phase's base charge is rounded to a whole number of cents *before* it is added to anything else, and the phase total is the sum of those already-rounded amounts plus the base charge. Accumulating fractional cents across several percentage lines and rounding the phase total once is explicitly the wrong algorithm and yields a total that differs by a cent. The discount benefit, the net monthly figures and both first-year totals then follow as exact integer arithmetic with no further rounding step, because every operand is already whole cents.

Measurement figures are rounded as follows: `typical_download_mbps` and `typical_upload_mbps` to two decimal places, `typical_latency_ms` to a whole millisecond, and `download_margin_pct` and `upload_margin_pct` to four decimal places. A complaint's `shortfall_ratio` is rounded to four decimal places and is always clamped into the range 0 through 1 inclusive.

Advertised speeds accept at most two decimal places, and a percentage fee rate accepts at most four decimal places; a value with finer precision is a malformed request.

### 2.8. Drafting Against a Plan Snapshot: Optimistic Concurrency

Two write operations depend on the client having an accurate picture of a plan's prices, fee lines and evidence pool at the moment it writes, and neither can be protected by a state precondition because both are legitimate at any point in the plan's life. Both therefore take an optimistic-concurrency token.

Creating a `PerformanceAttestation` requires `expected_plan_version` as a non-optional body field, carrying the client's last observed `version` of the `ServicePlan` named by `plan_id`. If that value does not equal the plan's current `version`, the create is rejected with `ERR_STALE_PLAN_VERSION` (HTTP 412). The check is what makes the write safe: a second attestation for the same plan legitimately supersedes the prior certified one, so no state check would ever catch a client that computed against an out-of-date plan.

Creating a `LabelVersion` likewise requires `expected_plan_version` as a non-optional body field carrying the client's last observed `version` of the plan named by `plan_id`, and a mismatch with the plan's current `version` is rejected with `ERR_STALE_PLAN_VERSION` (HTTP 412). A new draft label is always an admissible write, so the version check is the only thing guaranteeing that the itemisation on the draft was computed from the prices and fee lines the client actually saw.

No other operation takes a version field. In particular, publishing, withdrawing, certifying, triaging, resolving, filing, acknowledging and effecting all proceed without any client-supplied version.

### 2.9. The Plan Disclosure Posture Gate

Each `ServicePlan` carries a derived compliance gate, `label_posture`, whose value is one of `OPEN`, `RESTRICTED` or `FROZEN`. It is never written by a client; the server recomputes it after publishing a label, after withdrawing a label, after certifying an attestation, after amending a plan, after a complaint is *upheld* — a dismissal touches no input of the gate and recomputes nothing — and at the end of the invalidation cascade described in §3.3. A freshly created plan has no published label and is therefore `RESTRICTED`.

The recomputation considers the plan row itself together with its single published label — the label whose `publication_state` is `PUBLISHED`; draft, archived and withdrawn labels are excluded even when their display windows cover the clock. The rules are evaluated top to bottom and the first one that matches decides the value:

1. If the plan's `upheld_complaint_count` is three or more, the posture is `FROZEN`.
2. Otherwise, if the plan has a published label whose `substantiation_status` is `UNSUBSTANTIATED`, the posture is `FROZEN`.
3. Otherwise, if the plan has no published label at all, the posture is `RESTRICTED`.
4. Otherwise, if the plan's `price_disclosure_drift` is true, the posture is `RESTRICTED`.
5. Otherwise the posture is `OPEN`.

The gate has teeth on exactly two operations — recording a label disclosure and creating a plan-change notice. `OPEN` permits every disclosure channel and every notice type. `RESTRICTED` blocks a disclosure whose `channel` is `POINT_OF_SALE` and a notice whose `notice_type` is `PRICE_INCREASE`, answering `ERR_PLAN_POSTURE_RESTRICTED` (409), while `ACCOUNT_PORTAL` disclosures and `PLAN_CHANGE` notices continue to be accepted. `FROZEN` blocks every disclosure on either channel and every notice of either type, answering `ERR_PLAN_POSTURE_FROZEN` (409).

### 2.10. Segregation of Duties

Two operations are subject to maker-checker control, enforced by comparing operator identifiers for inequality. A `LabelVersion` may not be published by the officer who drafted it: if the publishing `X-User-ID` equals the label's `created_by_user_id`, the request is rejected with `ERR_SOD_SELF_PUBLISH` (403). A `LabelTranslation` may not be verified by the specialist who authored it: if the verifying `X-User-ID` equals the translation's `created_by_user_id`, the request is rejected with `ERR_SOD_SELF_REVIEW` (403). Both checks are evaluated after the target's state precondition and before the accessibility and referential prerequisites.

### 2.11. Order of Rejection

When several rules could reject the same request, the system evaluates them in the fixed order below and returns the first failure it finds. Text order elsewhere in this document does not imply independence — this ladder governs.

1. **Authentication.** Both `X-User-ID` and `X-User-Role` present and the role recognised, on every request — otherwise `ERR_UNAUTHENTICATED` (401).
2. **Authorisation.** The acting role is listed for the called operation, on every request — otherwise `ERR_UNAUTHORIZED` (403).
3. **Request shape.** On every request: required fields present, types correct, enum members recognised, numeric ranges honoured, pagination bounds respected, and the conditional-field rules in §3 satisfied — otherwise `ERR_INVALID_REQUEST` (400).
4. **Existence.** Every path segment and every body foreign key resolves, in the order described in §2.6 — otherwise the relevant 404 code.
5. **Subscriber scope.** For the `Subscriber` role, the target resolves to `X-User-ID` on the eleven scoped operations listed in §2.1 — otherwise `ERR_ACCOUNT_SCOPE_VIOLATION` (403).
6. **State.** The target satisfies the from-state and idempotency preconditions of the transition the operation drives, on every action that drives a transition — otherwise one of `ERR_LABEL_INVALID_STATE`, `ERR_ATTESTATION_INVALID_STATE`, `ERR_TEST_RUN_ALREADY_INVALIDATED`, `ERR_METHODOLOGY_ALREADY_PUBLISHED`, `ERR_TRANSLATION_INVALID_STATE`, `ERR_COMPLAINT_INVALID_STATE`, `ERR_CREDIT_ALREADY_VOIDED`, `ERR_INQUIRY_INVALID_STATE`, `ERR_INQUIRY_FILINGS_INCOMPLETE`, `ERR_NOTICE_INVALID_STATE` or `ERR_ACCOUNT_CHANGE_ALREADY_PENDING`, all 409.
7. **Plan version.** `expected_plan_version` matches the referenced plan's current `version`, on attestation creation and label creation — otherwise `ERR_STALE_PLAN_VERSION` (412).
8. **Segregation of duties.** On label publication and translation verification — otherwise `ERR_SOD_SELF_PUBLISH` or `ERR_SOD_SELF_REVIEW` (403).
9. **Disclosure posture.** On recording a label disclosure and creating a plan-change notice — otherwise `ERR_PLAN_POSTURE_FROZEN` or `ERR_PLAN_POSTURE_RESTRICTED` (409).
10. **Accessibility.** On recording a label disclosure and on publishing a label — otherwise `ERR_ACCESSIBILITY_FORMAT_UNSUPPORTED` (422).
11. **Temporal admissibility.** On recording a measurement run, creating a label, creating a notice and effecting a notice — otherwise `ERR_MEASUREMENT_WINDOW_FUTURE`, `ERR_LABEL_EFFECTIVE_NOT_AFTER_PUBLISHED`, `ERR_NOTICE_PERIOD_TOO_SHORT` or `ERR_NOTICE_NOT_DUE` (422).
12. **Uniqueness.** On creating a plan, a methodology document, a probe, a subscriber account, a regulator inquiry, a fee line item and a translation — otherwise `ERR_DUPLICATE_PLAN_CODE`, `ERR_DUPLICATE_DOCKET_NUMBER` (both 409) or `ERR_INVALID_REQUEST`.
13. **Interval geometry.** On creating a label and recording a measurement run — otherwise `ERR_LABEL_WINDOW_OVERLAP` or `ERR_PROBE_COOLDOWN_CONFLICT` (409), `ERR_RUN_DURATION_EXCEEDED` or `ERR_SAMPLE_OUTSIDE_WINDOW` (422).
14. **Evidence sufficiency.** On creating an attestation and on certifying one — otherwise `ERR_NO_ELIGIBLE_TEST_RUNS` or `ERR_INSUFFICIENT_SAMPLES` (409).
15. **Referential prerequisites.** On recording a measurement run, creating an attestation, publishing a label, recording a label disclosure, filing a complaint and filing a regulator response — otherwise `ERR_METHODOLOGY_NOT_PUBLISHED`, `ERR_ATTESTATION_NOT_CERTIFIED`, `ERR_TRANSLATION_COVERAGE_INCOMPLETE`, `ERR_FEE_ITEMIZATION_INCOMPLETE`, `ERR_TRANSLATION_NOT_AVAILABLE`, `ERR_LABEL_NOT_EFFECTIVE_FOR_SERVICE_DATE`, `ERR_LABEL_INVALID_STATE`, `ERR_COMPLAINT_NOT_TERMINAL` or `ERR_LABEL_NOT_SUBSTANTIATED_FOR_FILING`, all 409.
16. **Substantiated shortfall.** On resolving a complaint — otherwise `ERR_SHORTFALL_NOT_SUBSTANTIATED` (422).
17. **Substantiation margin.** On certifying an attestation — otherwise `ERR_SUBSTANTIATION_MARGIN_NOT_MET` (422).
18. **Reopen admissibility.** On reopening a complaint — otherwise `ERR_REOPEN_WINDOW_EXPIRED` (409).

Two consequences of this ladder deserve emphasis. A frozen posture surfaces as `ERR_PLAN_POSTURE_FROZEN` rather than being masked by the accessibility or translation checks that come later, and a stale `expected_plan_version` surfaces as `ERR_STALE_PLAN_VERSION` rather than as an interval-geometry conflict, even when the request would also have overlapped a sibling draft window.

### 2.12. Conserved Derived Quantities

Four running totals are conserved quantities: they are always recomputed from the rows that back them rather than adjusted by increments, so that a forward operation followed by its compensation leaves no drift.

`ServicePlan.evidence_sample_total` is the sum of `sample_count` over the measurement runs of that plan whose `status` is `INCLUDED`. `SubscriberAccount.credit_balance_cents` is the sum of `amount_cents` over the remediation credits of that account whose `status` is `ISSUED`, and `SubscriberAccount.remediation_count` is the count of those same rows. `LabelVersion.verified_locale_count` is the number of translations on that label whose `status` is `VERIFIED`. `ServicePlan.upheld_complaint_count` is the count of complaints whose account is subscribed to that plan and whose `state` is `UPHELD`.

`SubscriberAccount.audit_flag` is a pure function of the recomputed count: it is true while `remediation_count` is two or more, and it returns to false as soon as the count falls back below two.

## 3. Business Logic & Workflows

### 3.1. Defining a Service Plan and Its Fee Itemisation

A `ComplianceOfficer` opens a plan by supplying the marketing `plan_code` printed on the label (1 to 32 characters, globally unique and case-sensitive; a collision answers `ERR_DUPLICATE_PLAN_CODE`), the `display_name` that heads the label (1 to 120 characters), the `technology` disclosed to the consumer — one of `FIBER`, `CABLE`, `DSL`, `FIXED_WIRELESS` or `SATELLITE` — and the marketed speeds `advertised_download_mbps` and `advertised_upload_mbps`, both of which must be greater than zero. These two figures are the denominators the typical-speed claim is later measured against. Pricing is carried by `monthly_price_cents`, the post-promotional base charge in cents, which must be zero or more, together with `early_termination_fee_cents`, also zero or more, and `required_locales`, an array of one to five distinct BCP-47 locale tags each 2 to 16 characters long; an empty array, a repeated tag, or a tag outside that length is a malformed request.

Six further attributes are optional at creation and default when omitted. `intro_price_cents` is the introductory base charge in cents and defaults to null, meaning the plan has no promotional price; when present it must be zero or more. `intro_term_months` is the number of whole months the introductory charge applies, defaults to 0, is bounded between 0 and 24 inclusive, and must be at least 1 whenever `intro_price_cents` is present — a plan that names an introductory price with a zero term is rejected as a malformed request. `data_allowance_gb` defaults to null, which the label discloses as "Unlimited"; when present it must be at least 1. `overage_rate_cents_per_gb` is the charge in cents for each gigabyte beyond the allowance, defaults to 0, must be zero or more, and must be exactly 0 whenever `data_allowance_gb` is null. `etf_proration_policy` defaults to `FULL` and is one of `FULL`, `PRORATED_MONTHLY` or `NONE`. `discount_program_eligible` defaults to false and records whether the plan participates in the federal low-income discount programme.

A new plan starts with `label_posture` set to `RESTRICTED`, `evidence_sample_total` at 0, `upheld_complaint_count` at 0, `price_disclosure_drift` false, `active_label_version_id` null, `last_price_change_at` null and `version` at 1.

Amending a plan is a compliance officer's action too, and it always carries a `change_justification` alongside whichever of `monthly_price_cents`, `intro_price_cents`, `intro_term_months`, `data_allowance_gb`, `overage_rate_cents_per_gb`, `early_termination_fee_cents`, `etf_proration_policy` and `required_locales` is being changed. When the amendment supplies any of `monthly_price_cents`, `intro_price_cents`, `intro_term_months` or `early_termination_fee_cents` with a value that actually differs from the one the plan already holds — re-sending an identical value is not a price move and sets nothing — the plan's `price_disclosure_drift` is set to true, the same flag is set to true on the plan's published label, if it has one — because what the consumer can currently see no longer matches the plan of record — and `last_price_change_at` is set to the logical clock. The two coherence rules of creation — an `intro_term_months` of at least 1 whenever `intro_price_cents` is present, and an `overage_rate_cents_per_gb` of exactly 0 whenever `data_allowance_gb` is null — are re-checked against the merged record the amendment would produce, so an amendment that would leave the plan incoherent is a malformed request; and an amendment carrying only `change_justification`, changing no attribute at all, is still a legitimate write. Whether or not a price moved, the amendment recomputes the itemisation, the discount benefit and both first-year totals for every label of the plan whose `publication_state` is `DRAFT`; published, archived and withdrawn labels keep the figures pinned on them. The amendment then recomputes the plan's disclosure posture and increments the plan's `version`.

Each itemised fee on the label is a fee line item, added to a plan by a `ComplianceOfficer` with a `fee_code` (1 to 32 characters, unique among that plan's fee lines — a repeat is rejected as a malformed request), a consumer-facing `description` of 1 to 200 characters, a `label_category` naming the label block it is itemised under (`MONTHLY_RECURRING`, `ONE_TIME`, `EARLY_TERMINATION`, `DATA_OVERAGE` or `GOVERNMENT_TAX`), and a `basis` of either `FIXED` or `PCT_OF_MONTHLY_CHARGE`. A `FIXED` line must carry `amount_cents` (zero or more) and must leave `rate_pct` null; a `PCT_OF_MONTHLY_CHARGE` line must carry `rate_pct` — a fraction strictly greater than 0 and strictly less than 1, with at most four decimal places — and must leave `amount_cents` null. Because a one-off charge cannot sensibly be a percentage of a monthly bill, a line whose `label_category` is `ONE_TIME` must have `basis` set to `FIXED`. Two further attributes default: `applies_during` defaults to `ALWAYS` and may instead be `INTRO_ONLY` or `POST_PROMO_ONLY`, and `is_regulatory_recovery` defaults to false, marking a provider-imposed regulatory cost-recovery charge that the label must present as a provider fee rather than as a government tax. Each plan's fee lines are stored immutably against that plan and are never retired, so no status filter exists on them; the `plan_id` binding is fixed at creation. Adding a fee line recomputes the itemisation, the discount benefit and both first-year totals for every draft label of the plan. Fee lines can be listed for a plan in ascending `created_at` order — the same order the itemisation walks — optionally narrowed by `label_category`.

### 3.2. Measurement Infrastructure: Methodology Documents and Probe Panels

Before any speed can be measured, a `NetworkEngineer` authors the test methodology the label will cite. A methodology document is created with a `doc_code` (1 to 32 characters, globally unique; a collision is a malformed request), a `version_label` of 1 to 16 characters identifying the revision, a `methodology_url` of 1 to 300 characters pointing at the published document, the peak measurement window expressed as `peak_hours_start_utc_hour` (an inclusive UTC hour from 0 to 23) and `peak_hours_end_utc_hour` (an exclusive UTC hour from 1 to 24, which must be strictly greater than the start hour), a `min_samples_required` of at least 1, and a `max_run_duration_days` between 1 and 30 inclusive. It begins with `status` set to `DRAFT` and `published_at` null.

A methodology document is published by a `ComplianceOfficer`, not by its author — the drafting engineer defines the method, the compliance function attests that it is fit to cite. The transition from `DRAFT` to `PUBLISHED` requires that the document still be `DRAFT` (a second attempt answers `ERR_METHODOLOGY_ALREADY_PUBLISHED`) and that its peak window still be well-formed, with the exclusive end hour strictly greater than the inclusive start hour. Publication sets `published_at` to the logical clock and increments the document's `version`. `PUBLISHED` is terminal: only a published document may back a measurement run or an attestation, and a run or attestation that cites a document still in `DRAFT` is rejected with `ERR_METHODOLOGY_NOT_PUBLISHED`.

Measurement itself is performed by probe panels, registered by a `NetworkEngineer` with a `probe_code` (1 to 32 characters, globally unique; a collision is a malformed request), the `market_code` the panel measures (1 to 16 characters), a `panel_size` of at least 1 recording how many subscriber endpoints sit behind the panel — a figure disclosed in the methodology annex — and `max_concurrent_windows`, at least 1, which is the panel's aggregate capacity: the maximum number of live measurement windows on that probe whose intervals may cover any single instant.

### 3.3. Recording Measurement Runs and Withdrawing Them From the Evidence Pool

A `NetworkEngineer` records a completed measurement window against a plan by naming the `probe_id` that produced it, the `plan_id` whose typical-speed claim it supports, the `methodology_doc_id` it was measured under, the inclusive `window_start` and the inclusive `window_end` of the closed measurement interval, and the `samples` array itself. The array holds between 1 and 500 elements, and each element records an `observed_at` instant, a `download_mbps` and an `upload_mbps` both strictly greater than zero, and a `latency_ms` of at least 1. The run's `sample_count` is fixed at creation as the number of elements supplied, and the run opens with `status` `INCLUDED`, `invalidated_at` null, `invalidation_reason` null.

Four admissibility checks guard the recording, and they are decided in the ladder order of §2.11. `window_end` must be strictly after `window_start`, or the request is malformed. `window_end` must not be after the logical clock — measurement cannot be claimed for the future — and a future window answers `ERR_MEASUREMENT_WINDOW_FUTURE`. Then comes the probe's aggregate capacity: count the runs on the same probe whose `status` is `INCLUDED` and whose measurement interval, extended by a trailing cooldown buffer of 60 minutes past its own `window_end`, intersects the requested closed interval — the two intersect when the requested `window_start` is at or before the other run's buffered end and the other run's `window_start` is at or before the requested `window_end`. When that count reaches the probe's `max_concurrent_windows`, the recording is rejected with `ERR_PROBE_COOLDOWN_CONFLICT`. Then the run's own shape: the span from `window_start` to `window_end` must not exceed the cited document's `max_run_duration_days` days, or the request answers `ERR_RUN_DURATION_EXCEEDED`, and every sample's `observed_at` must fall inside the closed interval from `window_start` to `window_end` inclusive, or it answers `ERR_SAMPLE_OUTSIDE_WINDOW`. Finally the cited methodology document must be published.

Recording a run recomputes the plan's `evidence_sample_total` as the sum of `sample_count` over that plan's runs whose `status` is `INCLUDED`, and increments the plan's `version`. Runs can be read individually — samples and inclusion status included — or listed with filters on `probe_id`, `plan_id`, `methodology_doc_id` and `status`.

Withdrawing a run from the evidence pool is the most consequential single action in the system, and it is deliberately declared as a cascade. A `NetworkEngineer` invalidates a run by supplying a `reason`; the run must still be `INCLUDED`, or the request answers `ERR_TEST_RUN_ALREADY_INVALIDATED`. The transition `INCLUDED → INVALIDATED` then propagates in five hops:

- **Hop 1.** The run's `status` becomes `INVALIDATED`, `invalidated_at` is set to the logical clock, and `invalidation_reason` records the supplied `reason`.
- **Hop 2**, caused by hop 1. The plan's `evidence_sample_total` is recomputed as the sum of `sample_count` over that plan's remaining `INCLUDED` runs, and the plan's `version` is incremented.
- **Hop 3**, caused by hop 2. Every attestation of that plan whose `status` is `DRAFT` or `CERTIFIED` and whose pinned `min_samples_required` is now strictly greater than the plan's recomputed `evidence_sample_total` has its `status` set to `REVOKED` and its `revoked_reason` set to `EVIDENCE_BELOW_MINIMUM`. These are processed in ascending `created_at` order.
- **Hop 4**, caused by hop 3. Every label whose `attestation_id` names one of the attestations just revoked and whose `publication_state` is `PUBLISHED` has its `substantiation_status` set to `UNSUBSTANTIATED`. Its `publication_state` is deliberately left alone — a published label stays published while unsubstantiated, because the consumer is still being shown it.
- **Hop 5**, caused by hop 4. The plan's disclosure posture is recomputed, and it now yields `FROZEN`, because the plan's published label is unsubstantiated.

One further consequence follows from hop 4 without being part of the declared five-hop chain: every complaint whose `disputed_label_version_id` names that label and whose `state` is not `UPHELD`, `DISMISSED` or `WITHDRAWN` has `evidence_gap` set to true, recording that the disputed label lost its substantiation while the investigation was still open.

The invalidation carries a compensating invariant. After the transition completes, the plan's `evidence_sample_total` equals the sum of `sample_count` over that plan's runs whose `status` is `INCLUDED` — exactly the value it would have had if the invalidated run had never been recorded, with no accumulated drift.

### 3.4. Attesting Typical Speeds and Certifying the Claim

A typical-speed attestation is the bridge between raw measurement and a printable claim. A `NetworkEngineer` creates one by naming the `plan_id` whose speeds it computes, the `methodology_doc_id` it applies (which is pinned at creation and must be published at that moment), the `metric_variant` selecting one of the two documented algorithms, and the `expected_plan_version` described in §2.8. At creation the attestation pins a `methodology_snapshot` — a version-locked copy of the document's `version_label`, `peak_hours_start_utc_hour`, `peak_hours_end_utc_hour`, `min_samples_required`, `max_run_duration_days` and `methodology_url` — so that later revisions of the methodology cannot retroactively change what the attestation asserted. The attestation opens with `status` `DRAFT`, `certified_at` null and `revoked_reason` null.

The evidence pool is assembled from the plan's measurement runs whose `status` is `INCLUDED` and whose `methodology_doc_id` equals the attestation's own, taken in ascending `created_at` order. The ids of exactly those runs are recorded in `included_run_ids` as a snapshot that is never re-derived afterwards, and the samples of those runs are concatenated in that same run order (and, within a run, in the order they appear in the `samples` array). Runs that were invalidated, and runs measured under any other methodology document, are excluded. If the concatenation is empty, the create is rejected with `ERR_NO_ELIGIBLE_TEST_RUNS`.

The two variants then differ in which samples they pool. Under `PEAK_HOUR_MEDIAN` — the busy-hour claim the label's typical-speed line cites — only samples whose `observed_at` falls in the pinned peak window are pooled: the UTC hour of the observation must be at or after `peak_hours_start_utc_hour` and strictly before `peak_hours_end_utc_hour`. Under `ALL_HOUR_P20` — the conservative all-hours floor cited in the methodology annex — every sample is pooled regardless of hour. `pooled_sample_count` is the number of samples in the resulting pool, and an empty pool is likewise rejected with `ERR_NO_ELIGIBLE_TEST_RUNS`; this is the case where runs exist but none of their observations fall inside the peak window.

For `PEAK_HOUR_MEDIAN`, `typical_download_mbps` is the median of the pooled `download_mbps` values and `typical_upload_mbps` the median of the pooled `upload_mbps` values: sort the values ascending, take the single central value when the count is odd, and take the arithmetic mean of the two central values when the count is even. For `ALL_HOUR_P20`, both figures are the nearest-rank twentieth percentile of the corresponding pooled values: sort ascending and take the value whose one-based rank is the pool size multiplied by 0.20 and then rounded up to the next whole number. On identical run data the all-hours variant therefore yields a lower download figure than the peak-hour variant. Both figures are rounded half up to two decimal places.

`typical_latency_ms` is computed the same way under both variants: the nearest-rank ninety-fifth percentile of the pooled `latency_ms` values — sort ascending and take the value whose one-based rank is the pool size multiplied by 0.95 and then rounded up to the next whole number — rounded half up to a whole millisecond. Because the all-hours pool includes off-peak observations, it typically reports a higher ninety-fifth-percentile latency than the peak-hour pool on the same runs.

The two margins express how much of the marketed speed the measurement actually delivers. `download_margin_pct` is `typical_download_mbps` divided by the plan's `advertised_download_mbps`, and `upload_margin_pct` is `typical_upload_mbps` divided by `advertised_upload_mbps`, each rounded half up to four decimal places.

Creating an attestation for a plan that already has a certified attestation is legitimate and supersedes it: the older attestation's `status` moves from `CERTIFIED` to `SUPERSEDED` — by invariant there is at most one certified attestation per plan — while any label already pinned to the superseded attestation keeps its pinned typical figures and its `substantiation_status` untouched, because a published label discloses what it disclosed. Creating an attestation also increments the plan's `version`.

Certification is a `ComplianceOfficer`'s act and moves an attestation from `DRAFT` to `CERTIFIED`. It requires that the attestation still be `DRAFT`, or the request answers `ERR_ATTESTATION_INVALID_STATE`; that `pooled_sample_count` be at least the pinned `min_samples_required`, with an inclusive boundary, or the request answers `ERR_INSUFFICIENT_SAMPLES`; and that both `download_margin_pct` and `upload_margin_pct` be at least 0.80 — again an inclusive boundary, so exactly 0.8000 passes — or the request answers `ERR_SUBSTANTIATION_MARGIN_NOT_MET`. Certification sets `certified_at` to the logical clock and increments the attestation's `version`. `SUPERSEDED` and `REVOKED` are the attestation's terminal states.

Certification also repairs a broken claim. When the plan has a published label whose `substantiation_status` is `UNSUBSTANTIATED`, certifying a replacement attestation for that same plan re-pins the label's `attestation_id` to the newly certified attestation, refreshes the label's pinned `typical_download_mbps`, `typical_upload_mbps`, `typical_latency_ms` and `methodology_url_snapshot` from it, and moves the label's `substantiation_status` from `UNSUBSTANTIATED` back to `SUBSTANTIATED` without touching its `publication_state`. The plan's posture is then recomputed — returning to `OPEN` when the published label is substantiated, `price_disclosure_drift` is false and `upheld_complaint_count` is below three — and the plan's `version` is incremented. Attestations can be read individually or listed with filters on `plan_id`, `methodology_doc_id` and `status`.

### 3.5. Drafting a Consumer Label: Pricing Disclosure, Discount and First-Year Totals

A `ComplianceOfficer` drafts a label for a plan by naming the `plan_id`, the inclusive `effective_from` instant at which the label starts being displayable, the `accessibility_conformance` of the rendered content — either `NONE` or `WCAG_AA` — and the `expected_plan_version` from §2.8. Two fields are optional: `effective_until`, the exclusive end of the display window, which defaults to null meaning open-ended and, when supplied, must be strictly after `effective_from`; and `discount_program_applied`, which when omitted defaults to the plan's current `discount_program_eligible` value. The draft receives `version_seq`, a per-plan monotonic sequence number computed as one more than the highest `version_seq` among that plan's existing labels and starting at 1 for the plan's first label, and it records the drafting officer's `X-User-ID` in `created_by_user_id`. It opens with `publication_state` `DRAFT` and `substantiation_status` `PENDING_EVIDENCE`, and with `attestation_id`, `typical_download_mbps`, `typical_upload_mbps`, `typical_latency_ms` and `methodology_url_snapshot` all null, `published_by_user_id`, `published_at`, `archived_at` and `withdrawn_at` null, `price_disclosure_drift` false and `verified_locale_count` at 0.

Two geometric rules guard the draft. Its `effective_from` must be strictly after the `effective_from` of the plan's currently published label, or the draft is rejected with `ERR_LABEL_EFFECTIVE_NOT_AFTER_PUBLISHED` — a new disclosure cannot claim to have started before the one it will replace. And the requested half-open window from `effective_from` up to but excluding `effective_until` must not overlap the window of any other label of the same plan whose `publication_state` is `DRAFT`; a null `effective_until` is treated as extending to positive infinity. Two windows overlap when the new `effective_from` is strictly before the other's `effective_until` and the other's `effective_from` is strictly before the new `effective_until`, which makes exact adjacency legal — a new window starting precisely where a sibling draft's window ends does not overlap. An overlap answers `ERR_LABEL_WINDOW_OVERLAP`. Drafting a label also increments the plan's `version`.

Drafting the label computes the entire priced face of the disclosure. Two pricing phases exist. The introductory phase's base charge is the plan's `intro_price_cents`, and the phase is omitted entirely when that value is null. The post-promotional phase's base charge is the plan's `monthly_price_cents` and is always present.

The fee lines that enter a phase are the plan's fee lines whose `label_category` is `MONTHLY_RECURRING` or `GOVERNMENT_TAX` and whose `applies_during` is `ALWAYS`, together with — for the introductory phase only — those whose `applies_during` is `INTRO_ONLY`, and — for the post-promotional phase only — those whose `applies_during` is `POST_PROMO_ONLY`. They are processed in ascending `created_at` order. A line whose `basis` is `FIXED` contributes its `amount_cents` unchanged. A line whose `basis` is `PCT_OF_MONTHLY_CHARGE` contributes its `rate_pct` multiplied by that phase's base charge, rounded half up to a whole number of cents at that point, before it is added to anything. The percentage is taken against the phase's base charge alone: never against the base plus the fixed fee lines, and never against a net figure after the discount benefit has been deducted. Each processed line is emitted into the label's `fee_itemization` array as an entry recording exactly four keys — the line's `fee_code`, its `label_category`, the `phase` it was itemised under, and the resulting `amount_cents` — and nothing else. A line is emitted once per phase it applies to, so a `MONTHLY_RECURRING` or `GOVERNMENT_TAX` line whose `applies_during` is `ALWAYS` on a plan that has an introductory price produces two entries sharing a `fee_code` and differing in `phase`. The array is ordered phase-major: every introductory-phase entry first, in ascending `created_at` of the fee line, then every post-promotional entry in that same line order, and finally the one-time entries described in the next paragraph. It is present as an empty array, never absent, when the plan has no itemisable fee line at all. The phase's gross monthly total is the phase base charge plus the sum of those already-rounded line amounts, and it lands in `monthly_total_intro_cents` for the introductory phase — null when the plan has no introductory price — and in `monthly_total_post_promo_cents` for the post-promotional phase.

Separately, the plan's fee lines whose `label_category` is `ONE_TIME` are walked in ascending `created_at` order, each emitted into `fee_itemization` with its `phase` recorded as `ONE_TIME`, and their `amount_cents` summed into `one_time_fee_total_cents`. The `phase` recorded on an itemisation entry is therefore one of `INTRO`, `POST_PROMO` or `ONE_TIME`. Fee lines whose `label_category` is `EARLY_TERMINATION` or `DATA_OVERAGE` are disclosed in their own label blocks and are excluded from both monthly totals, from the one-time total, and from the `fee_itemization` array itself — no entry is ever emitted for them under any phase.

The low-income discount benefit is derived from the gross totals, not folded into them. When `discount_program_applied` is false, both `discount_program_benefit_intro_cents` and `discount_program_benefit_post_promo_cents` are 0. When it is true, each phase's benefit is the lesser of 3,000 cents — a thirty-dollar monthly cap — and that phase's gross monthly total, so the benefit clamps at the bill and the net can reach exactly zero but never goes negative. `net_monthly_intro_cents` is `monthly_total_intro_cents` minus `discount_program_benefit_intro_cents` and is null when there is no introductory phase, in which case the introductory benefit is 0. `net_monthly_post_promo_cents` is `monthly_total_post_promo_cents` minus `discount_program_benefit_post_promo_cents`. The evaluation order is pinned and only looks circular: the gross phase totals come first, including every percentage line computed against the gross base; the benefit is derived from that gross total; the net is the gross minus the benefit. Percentage lines are never recomputed against the net amount, and the benefit is never subtracted from the base before the percentage lines are computed.

The label then discloses first-year cost twice, side by side, so that a consumer can see both the promotional reality and the ongoing cost. The number of months billed at the introductory net is the lesser of the plan's `intro_term_months` and twelve. Under the promotion-weighted variant, `first_year_total_promo_weighted_cents` is `one_time_fee_total_cents` plus `net_monthly_intro_cents` multiplied by that number of introductory months, plus `net_monthly_post_promo_cents` multiplied by the remaining months of the twelve-month disclosure year. Under the post-promotional annualised variant, `first_year_total_post_promo_cents` is `one_time_fee_total_cents` plus `net_monthly_post_promo_cents` multiplied by all twelve months, ignoring the introductory price entirely. The promotion-weighted figure is the one the label headlines as its first-year total whenever the plan has an introductory price, and is the figure a point-of-sale disclosure must show; the annualised figure sits beside it as the ongoing annual cost after the promotional period. Whenever the post-promotional net exceeds the introductory net and at least one introductory month is billed, the annualised figure is strictly the larger of the two. When the plan has no introductory price, no introductory months are billed and the two variants coincide. Both are exact integer arithmetic on whole cents with no rounding step.

Drafting also snapshots three plan attributes onto the label so the archive stays readable after the plan moves on: `etf_disclosure_cents` copies the plan's `early_termination_fee_cents` at compute time for the label's early-termination block, `data_allowance_gb_snapshot` copies `data_allowance_gb` (null meaning the label discloses "Unlimited"), and `overage_rate_cents_per_gb_snapshot` copies `overage_rate_cents_per_gb`.

### 3.6. Translating, Publishing, Archiving and Withdrawing a Label

Label content must be readable in every locale the plan is obliged to serve. A `LocalizationSpecialist` adds a translation to a drafted label with a `locale` — a BCP-47 tag of 2 to 16 characters, unique among that label's translations, a repeat being a malformed request — a `translated_summary` of 1 to 2,000 characters rendering the label's disclosure text, and an optional `machine_translated` flag that defaults to false. The parent label's `publication_state` must still be `DRAFT`: translations may neither be added to nor verified under a label that has already been published, archived or withdrawn, and an attempt answers `ERR_LABEL_INVALID_STATE`. The flag is recorded for audit only; a machine-produced translation is verified under exactly the same rules as a human one. The translation opens with `status` `DRAFT`, `verified_by_user_id` and `verified_at` null, and records its author's `X-User-ID` in `created_by_user_id`. Adding one increments the parent label's `version`.

Verification moves a translation from `DRAFT` to `VERIFIED`, its terminal state. The translation must still be `DRAFT`, or the request answers `ERR_TRANSLATION_INVALID_STATE`; the parent label's `publication_state` must still be `DRAFT`, or it answers `ERR_LABEL_INVALID_STATE`, because translations are settled before the disclosure goes live and not after; and the verifying `X-User-ID` must differ from the translation's `created_by_user_id`, or it answers `ERR_SOD_SELF_REVIEW`. Verification sets `status` to `VERIFIED`, records `verified_by_user_id` as the verifying `X-User-ID` and `verified_at` as the logical clock, increments the parent label's `verified_locale_count` by one, and increments the parent label's `version`. A label's translations can be listed with filters on `locale` and `status`.

Publication is the moment a disclosure becomes what consumers see, and it is guarded by six preconditions, checked in the order of §2.11's ladder. The label's `publication_state` must be `DRAFT`, or the request answers `ERR_LABEL_INVALID_STATE`. The publishing `X-User-ID` must differ from `created_by_user_id`, or it answers `ERR_SOD_SELF_PUBLISH`. The label's `accessibility_conformance` must be `WCAG_AA` — a label that has not been brought to that conformance level cannot be published at all — or it answers `ERR_ACCESSIBILITY_FORMAT_UNSUPPORTED`. Then the referential prerequisites, in this order: the plan must have an attestation whose `status` is `CERTIFIED`, or `ERR_ATTESTATION_NOT_CERTIFIED`; every locale in the plan's `required_locales` must have a translation on this label whose `status` is `VERIFIED`, or `ERR_TRANSLATION_COVERAGE_INCOMPLETE`; and every fee line of the plan whose `label_category` is `MONTHLY_RECURRING` must appear in the label's `fee_itemization` for at least one phase, or `ERR_FEE_ITEMIZATION_INCOMPLETE`. The last of these catches, for example, an `INTRO_ONLY` recurring fee on a plan that has no introductory price: the line exists but no phase itemises it, so the label would silently omit a recurring charge.

Publication then performs the transition `DRAFT → PUBLISHED` on the publication dimension and, simultaneously and independently, `PENDING_EVIDENCE → SUBSTANTIATED` on the substantiation dimension, and it carries out the following:

- It pins `attestation_id` to the plan's certified attestation. The candidate set is the attestations whose plan is this plan and whose `status` is `CERTIFIED` — at most one by invariant — ranked by `certified_at` descending with `created_at` ascending as the tie-break; an empty candidate set is the `ERR_ATTESTATION_NOT_CERTIFIED` case above.
- It copies `typical_download_mbps`, `typical_upload_mbps`, `typical_latency_ms` and `methodology_url_snapshot` from that attestation onto the label, so those three previously null figures become non-null and the printed claim is frozen against later measurement changes.
- It sets `substantiation_status` to `SUBSTANTIATED`, `publication_state` to `PUBLISHED`, `published_at` to the logical clock, and `published_by_user_id` to the publishing `X-User-ID`.
- It archives the plan's previous published label: that predecessor's `publication_state` becomes `ARCHIVED`, its `archived_at` is set to the logical clock, and its `effective_until` is truncated to the new label's `effective_from` when it was previously null or later than that instant. Disclosures already recorded against the archived label stay readable and keep their `disclosed_label_version_seq`.
- It sets the plan's `active_label_version_id` to this label's `id`, and clears drift on both records — the plan's `price_disclosure_drift` and this label's `price_disclosure_drift` are both set to false, because what the consumer can now see is once again the plan of record.
- It clears the evidence gap: every complaint whose `disputed_label_version_id` belongs to this plan and whose `state` is not `UPHELD`, `DISMISSED` or `WITHDRAWN` has `evidence_gap` set to false.
- It recomputes the plan's disclosure posture and increments the plan's `version`.

The two state dimensions on a label move independently on the same record. `publication_state` walks `DRAFT`, `PUBLISHED`, and then either `ARCHIVED` or `WITHDRAWN`, the last two being terminal. `substantiation_status` walks `PENDING_EVIDENCE` to `SUBSTANTIATED` at publication, may fall to `UNSUBSTANTIATED` when the pinned attestation is revoked by the invalidation cascade of §3.3, and may return to `SUBSTANTIATED` when a replacement attestation is certified as described in §3.4 — none of which changes `publication_state`.

Withdrawal is the compensating action for a publication that should not have happened, and it is a `ComplianceOfficer`'s act carrying a `reason`. The label's `publication_state` must be `PUBLISHED`, or the request answers `ERR_LABEL_INVALID_STATE`. Withdrawal sets `publication_state` to `WITHDRAWN` and `withdrawn_at` to the logical clock, then restores the predecessor it displaced: among the same plan's labels whose `publication_state` is `ARCHIVED`, ranked by `version_seq` descending with `created_at` ascending as the tie-break, the first one is returned to `publication_state` `PUBLISHED`, its `archived_at` is cleared, and its `effective_until` is restored to the value it held before publication truncated it. When the candidate set is empty no restoration happens. The plan's `active_label_version_id` is then set to the restored label's `id`, or to null when there was nothing to restore, the plan's posture is recomputed, and the plan's `version` is incremented.

Labels are readable individually — this is the archival read path for historical disclosures — and listable with filters on `plan_id`, on `attestation_id` to find every label pinned to a given attestation, on `publication_state`, and on an `effective_on` date that the label's display window must cover. Disclosure events recorded against a single label can also be listed for archival and regulator evidence, optionally narrowed by `channel`.

### 3.7. The Retail Surface: Enrolment, Disclosure and Change Notices

A `RetailAgent` enrols a consumer by creating a subscriber account with an `account_code` (1 to 32 characters, globally unique; a collision is a malformed request), the `plan_id` the account subscribes to, a `preferred_locale` of 2 to 16 characters naming the locale the account prefers for label content, and a `service_start_date`. Two attributes are optional: `accessibility_need`, which defaults to `NONE` and may instead be `SCREEN_READER` or `LARGE_PRINT`, and `discount_program_enrolled`, which defaults to false and records the consumer's enrolment in the low-income discount programme. The account opens with `subscription_state` `ACTIVE`, `credit_balance_cents` at 0, `remediation_count` at 0, `audit_flag` false and `last_disclosed_label_version_id` null.

The account's `pricing_phase` is derived, never supplied. Take the whole number of thirty-day months elapsed between the account's `service_start_date` and the logical clock — that is, the elapsed span in seconds divided by 2,592,000 seconds and rounded down to a whole number. If the account's plan has no `intro_price_cents`, the phase is `POST_PROMO`. Otherwise, if that elapsed month count is strictly less than the plan's `intro_term_months`, the phase is `INTRO`; otherwise it is `POST_PROMO`. The boundary is exclusive, so an elapsed count exactly equal to `intro_term_months` is already `POST_PROMO`. A clock positioned before the `service_start_date` produces an elapsed count of zero or less and therefore `INTRO` for a plan that has an introductory price. The phase is evaluated at enrolment, whenever a notice is effected, and on every read that returns an account. Accounts can be listed with filters on `plan_id` and `subscription_state`.

Recording that the label was displayed to a consumer is the point where most of the system's gates converge. A `RetailAgent` or the `Subscriber` themselves records a disclosure against the account by supplying the `channel` — `POINT_OF_SALE` or `ACCOUNT_PORTAL` — the `locale` in which the content was rendered (2 to 16 characters), and the `accessible_format` served, which is one of `STANDARD_WEB`, `SCREEN_READER` or `LARGE_PRINT`. The label version is chosen by the server and is never supplied by the client.

Four gates apply, in ladder order. First the plan's disclosure posture: a frozen plan blocks both channels with `ERR_PLAN_POSTURE_FROZEN`, and a restricted plan blocks the `POINT_OF_SALE` channel with `ERR_PLAN_POSTURE_RESTRICTED` while continuing to permit `ACCOUNT_PORTAL`. Then accessibility: when the account's `accessibility_need` is `SCREEN_READER` the `accessible_format` must be `SCREEN_READER`, and when it is `LARGE_PRINT` the format must be `LARGE_PRINT`. A violation of that rule answers `ERR_ACCESSIBILITY_FORMAT_UNSUPPORTED`. Then label selection, described below, which can fail with `ERR_LABEL_NOT_EFFECTIVE_FOR_SERVICE_DATE`. A second accessibility rule — that any format other than `STANDARD_WEB` requires the selected label's `accessibility_conformance` to be `WCAG_AA`, on pain of the same `ERR_ACCESSIBILITY_FORMAT_UNSUPPORTED` — necessarily reads the label that selection chose and is therefore evaluated immediately after selection succeeds rather than with the rule above it, so a request asking for a non-standard format against a plan with no label in effect answers `ERR_LABEL_NOT_EFFECTIVE_FOR_SERVICE_DATE` and not the accessibility code. Then translation availability: the requested `locale` must have a translation on the selected label whose `status` is `VERIFIED`, or the request answers `ERR_TRANSLATION_NOT_AVAILABLE`.

Selection considers the labels of the account's current plan whose `publication_state` is `PUBLISHED` and whose half-open display window contains the logical clock — that is, whose `effective_from` is at or before the clock and whose `effective_until` is either null or strictly after the clock. Draft, archived and withdrawn labels are excluded even when their windows would cover the clock. Candidates are ranked by `version_seq` descending, with `created_at` ascending as a tie-break that is unreachable in practice because `version_seq` is unique per plan, and the first candidate is selected. An empty candidate set answers `ERR_LABEL_NOT_EFFECTIVE_FOR_SERVICE_DATE`. The disclosure then records `label_version_id` as the selected label, `disclosed_label_version_seq` as that label's `version_seq`, `disclosed_net_monthly_cents` as the phase-appropriate figure — the label's `net_monthly_intro_cents` when the account's `pricing_phase` is `INTRO` and its `net_monthly_post_promo_cents` otherwise, copied as whole cents with no re-rounding — and `disclosed_by_user_id` as the acting `X-User-ID`. The account's `last_disclosed_label_version_id` is updated to the selected label's id. An account's disclosure history is listable, including disclosures of labels since archived, optionally narrowed by `channel`.

Plan changes and price increases reach the consumer through a notice. A `RetailAgent` creates one naming the `account_id` being notified, the `target_plan_id` the account moves to when the notice is effected, a `notice_type` of either `PLAN_CHANGE` or `PRICE_INCREASE`, the `effective_date` on which the change takes effect, and a consumer-facing `reason` of 1 to 500 characters. The account's `subscription_state` must be `ACTIVE`; an account that already has a notice outstanding answers `ERR_ACCOUNT_CHANGE_ALREADY_PENDING`. The disclosure posture that applies is that of the *source* plan — the plan the account currently holds — and never the target plan's, so a frozen source plan blocks any notice and a restricted source plan blocks a `PRICE_INCREASE` notice. And the `effective_date` must be at least thirty whole days after the logical clock, or the request answers `ERR_NOTICE_PERIOD_TOO_SHORT`.

Creating the notice records `notice_days` as the whole number of days between the logical clock at creation and the `effective_date` — the span in seconds divided by 86,400 and rounded down — copies the account's current `plan_id` into `source_plan_id` as a denormalised record of the plan being left (never client-supplied), and takes `disclosed_net_monthly_cents` from the target plan's published label, specifically that label's `net_monthly_post_promo_cents` — null when the target plan has no published label at all. It also moves the account from `ACTIVE` to `PENDING_CHANGE` and increments the account's `version`. The notice itself opens in state `SENT` with `acknowledged_at` and `effected_at` null.

The early termination fee disclosed on the notice is always the one owed on the plan being *left*, never the target plan's, and it is computed as `etf_disclosed_cents` by a decaying schedule keyed on the source plan's `etf_proration_policy`. Under `NONE` the disclosed fee is 0. Under `FULL` it is the source plan's `early_termination_fee_cents` in full. Under `PRORATED_MONTHLY` it decays with the introductory term: take the whole number of thirty-day months elapsed between the account's `service_start_date` and the logical clock (the elapsed seconds divided by 2,592,000, rounded down), subtract that from the source plan's `intro_term_months` and treat any negative result as zero to obtain the remaining months, then multiply the source plan's `early_termination_fee_cents` by those remaining months, divide by the source plan's `intro_term_months` — or by 1 when that term is 0 — and round half up to a whole number of cents. The result is a step function on whole elapsed months that reaches 0 once the elapsed month count equals or exceeds the introductory term.

The notice then walks `SENT → ACKNOWLEDGED → EFFECTED`, with `EFFECTED` terminal. Only the `Subscriber` who owns the account may acknowledge, and only from `SENT`; an attempt from any other state answers `ERR_NOTICE_INVALID_STATE`, and an attempt by a subscriber whose `X-User-ID` does not equal the notice's `account_id` answers `ERR_ACCOUNT_SCOPE_VIOLATION`. Acknowledgement records `acknowledged_at` as the logical clock. Effecting the notice is a `RetailAgent`'s act; the notice must be `ACKNOWLEDGED`, or the request answers `ERR_NOTICE_INVALID_STATE`, and the logical clock must have reached the `effective_date`, or it answers `ERR_NOTICE_NOT_DUE`. Effecting sets `state` to `EFFECTED` and `effected_at` to the logical clock; on a `PLAN_CHANGE` notice it moves the account's `plan_id` to the notice's `target_plan_id`; it returns the account's `subscription_state` from `PENDING_CHANGE` to `ACTIVE`; and it recomputes the account's `pricing_phase` against whichever plan the account now holds. Notices are readable individually and listable with filters on `account_id`, `target_plan_id` and `state`.

### 3.8. Consumer Complaints, Investigation and Remediation

A complaint is filed either by the `Subscriber` themselves or by a `ComplaintAnalyst` on their behalf, naming the `account_id` of the complaining subscriber, the `disputed_label_version_id` whose claims are disputed, an `allegation_type` of `SPEED_SHORTFALL`, `LATENCY_SHORTFALL`, `RELIABILITY_OUTAGE` or `FEE_MISMATCH`, the `service_observed_date` on which the shortfall was observed, the `affected_days` of degraded service claimed (between 1 and 60 inclusive), and a `narrative` of 1 to 2,000 characters describing the problem. Three measurement fields are conditional: `measured_download_mbps` is required when the allegation is `SPEED_SHORTFALL` and `measured_latency_ms` is required when it is `LATENCY_SHORTFALL`, while `measured_upload_mbps` is always optional; the two speed figures must be zero or more when present and the latency figure at least 1. All three default to null.

The disputed label must be a label a consumer could actually have been shown on the date in question: its display window must cover the `service_observed_date`, and its pinned typical figures must be non-null. A label that was never published carries null typical figures and therefore cannot be disputed — the intake answers `ERR_LABEL_INVALID_STATE`. A complaint opens with `state` `INTAKE`, `resolution` `NONE`, `severity` `NONE`, `shortfall_ratio` null, `reopened_count` at 0, `investigation_cycles` at 0, `evidence_gap` false and `remediation_credit_cents` at 0, with `triaged_at`, `sla_due_at`, `resolved_at`, `resolution_note`, `info_request_note` and `credit_basis` all null. Complaints are readable individually and listable with filters on `account_id`, `disputed_label_version_id` and `state`.

Triage is a `ComplaintAnalyst`'s act carrying a `priority_note`, and it moves the complaint `INTAKE → TRIAGED`; from any other state it answers `ERR_COMPLAINT_INVALID_STATE`. Triage sets `triaged_at` to the logical clock and `sla_due_at` to thirty days after `triaged_at`, starting the response clock the regulator will later measure against.

Opening the investigation moves the complaint `TRIAGED → UNDER_INVESTIGATION` and computes the shortfall assessment. When the analyst needs more from the consumer, requesting information carries an `info_request_note`, moves the complaint `UNDER_INVESTIGATION → INFO_REQUESTED` and records that note as the most recent request. Resuming afterwards moves it `INFO_REQUESTED → UNDER_INVESTIGATION`, increments `investigation_cycles` by one, and recomputes the assessment against the same pinned label figures — the loop between these two states may be walked any number of times, and each return through it is counted. Each of these three transitions requires its own from-state and otherwise answers `ERR_COMPLAINT_INVALID_STATE`.

The assessment produces `shortfall_ratio` and `severity` from the complaint together with the pinned typical figures of the disputed label. For a `SPEED_SHORTFALL`, take the label's pinned `typical_download_mbps` as the claimed figure and the complaint's `measured_download_mbps` as the observed figure, subtract the observed from the claimed, treat a negative difference as zero, divide by the claimed figure, and round half up to four decimal places. For a `LATENCY_SHORTFALL`, the allowed latency is the label's pinned `typical_latency_ms` plus a tolerance of 5 milliseconds; the excess is the complaint's `measured_latency_ms` minus that allowance, with a negative result treated as zero; the ratio is that excess divided by the label's pinned `typical_latency_ms`, capped at 1, rounded half up to four decimal places. For a `RELIABILITY_OUTAGE`, the ratio is the complaint's `affected_days` divided by a thirty-day reliability window, capped at 1 and rounded half up to four decimal places. For a `FEE_MISMATCH` — a pricing dispute that carries no speed shortfall by definition — the ratio is exactly zero.

`severity` follows from the ratio with inclusive thresholds: a ratio of 0.50 or more is `SEVERE`, a ratio of 0.25 or more but below 0.50 is `MODERATE`, any ratio strictly greater than zero but below 0.25 is `MINOR`, and a ratio of exactly zero is `NONE`. Exactly 0.5000 is therefore `SEVERE` and exactly 0.2500 is `MODERATE`.

Resolution carries a `finding` of either `UPHELD` or `DISMISSED`, a `resolution_note` recording the analyst's rationale, and — only when the finding is `UPHELD` — a `credit_basis` of either `PRORATA_DAYS` or `FLAT_SEVERITY_TIER`. A `credit_basis` supplied with a `DISMISSED` finding, or omitted with an `UPHELD` finding, is a malformed request. Either resolution requires the complaint to be `UNDER_INVESTIGATION`, and otherwise answers `ERR_COMPLAINT_INVALID_STATE`. Upholding additionally requires the assessed `severity` not to be `NONE`, so that no credit is ever issued against a zero shortfall; a zero-shortfall uphold answers `ERR_SHORTFALL_NOT_SUBSTANTIATED`.

The credit amount is computed at resolution. The base is the pinned net monthly charge of the disputed label for the account's current phase: `net_monthly_intro_cents` when the account's `pricing_phase` is `INTRO` and `net_monthly_post_promo_cents` otherwise. When `severity` is `NONE` the amount is 0 and no clamping applies. Otherwise a raw figure is produced from the chosen basis. Under `PRORATA_DAYS` the raw figure is the base multiplied by the complaint's `shortfall_ratio`, multiplied by the lesser of the complaint's `affected_days` and thirty days, divided by thirty. Under `FLAT_SEVERITY_TIER` the raw figure is a fixed tier amount: 1,000 cents for `MINOR`, 2,500 cents for `MODERATE`, 5,000 cents for `SEVERE` and 0 for `NONE`. The clamping order is pinned: round the raw figure half up to a whole number of cents *first*, then raise it to a floor of 500 cents if it is below that, and only then cap it at the base. The floor never lifts a zero-severity complaint above 0, because that case returns before any clamping, and the base ceiling means a flat-tier credit can never exceed one month's net charge.

Upholding a complaint then propagates in four hops:

- **Hop 1.** The complaint's `state` and `resolution` both become `UPHELD`, `resolved_at` is set to the logical clock, `resolution_note` records the supplied note, `credit_basis` records the supplied basis, and `remediation_credit_cents` records the computed amount.
- **Hop 2**, caused by hop 1. A remediation credit is created carrying `complaint_id` naming this complaint, `account_id` copied from the complaint's own account (a denormalised copy, never client-supplied), `basis` copied from the complaint's `credit_basis`, `amount_cents` set to the computed amount and immutable thereafter, `status` `ISSUED`, and `issued_by_user_id` set to the resolving analyst's `X-User-ID`, with `voided_by_user_id`, `voided_at` and `void_reason` all null.
- **Hop 3**, caused by hop 2. The account's `credit_balance_cents` is recomputed as the sum of `amount_cents` over that account's credits whose `status` is `ISSUED`, `remediation_count` as the count of those same rows, and the account's `version` is incremented.
- **Hop 4**, caused by hop 3. The account's `audit_flag` is set to true when the recomputed `remediation_count` is two or more, and to false otherwise.

One further consequence follows from hop 1 without being part of the declared four-hop chain: the plan the account is subscribed to has its `upheld_complaint_count` incremented by one, its disclosure posture recomputed — which drops it to `FROZEN` once the count reaches three — and its `version` incremented.

Dismissal is deliberately narrower. It sets `state` and `resolution` to `DISMISSED`, `resolved_at` to the logical clock and `resolution_note` to the supplied note. No remediation credit is created, the account's `credit_balance_cents` is untouched, and the plan's `upheld_complaint_count` does not move; nothing at all is written to the plan, so its disclosure posture is not recomputed and its `version` does not change either.

`DISMISSED` is not terminal. A `ComplaintAnalyst` may reopen a dismissed complaint with a `reopen_reason`, moving it `DISMISSED → UNDER_INVESTIGATION`. Two admissibility rules apply: the whole number of days between `resolved_at` and the logical clock — the elapsed seconds divided by 86,400, rounded down — must be no more than thirty, an inclusive boundary; and `reopened_count` must still be below two. A violation of either answers `ERR_REOPEN_WINDOW_EXPIRED`. Reopening increments `reopened_count` by one and clears the resolution, setting `resolved_at` back to null, `resolution` back to `NONE` and `resolution_note` back to null. Reopening from any state other than `DISMISSED` answers `ERR_COMPLAINT_INVALID_STATE`.

The complaining `Subscriber` may withdraw their own complaint from any of its four non-terminal states — `INTAKE`, `TRIAGED`, `UNDER_INVESTIGATION` or `INFO_REQUESTED` — by supplying a `withdraw_reason`. All four withdrawals behave identically: `state` and `resolution` both become `WITHDRAWN` and `resolved_at` is set to the logical clock. A withdrawal attempted by a subscriber whose `X-User-ID` does not equal the complaint's `account_id` answers `ERR_ACCOUNT_SCOPE_VIOLATION`. `UPHELD` and `WITHDRAWN` are the complaint's terminal states.

A `ComplianceOfficer` may void an issued credit with a `void_reason`; a credit already voided answers `ERR_CREDIT_ALREADY_VOIDED`. Voiding sets the credit's `status` to `VOIDED`, `voided_at` to the logical clock, `voided_by_user_id` to the officer's `X-User-ID`, and `void_reason` to the supplied reason, then compensates: the account's `credit_balance_cents` is recomputed as the sum of `amount_cents` over that account's remaining `ISSUED` credits, `remediation_count` as the count of those rows, and `audit_flag` re-derived as true exactly when that recomputed count is two or more. The complaint's `remediation_credit_cents` is set back to 0 — and when it already reads 0 the complaint is not written at all, so its `updated_at` and `version` do not move — while the complaint's `state` stays `UPHELD` and the plan's `upheld_complaint_count` is left unchanged — the finding stands even though the money is reversed. The compensating invariant is that after voiding, the account's `credit_balance_cents` again equals the sum of `amount_cents` over its `ISSUED` credits: identical to the value it held before the credit was ever issued. Credits are readable individually and listable per complaint with an optional `status` filter.

### 3.9. Regulator Dockets and Evidence Filings

When a regulator opens a docket about a consumer complaint, a `RegulatoryLiaison` records it by naming the `complaint_id` under enquiry, the `docket_number` (1 to 32 characters, globally unique; a collision answers `ERR_DUPLICATE_DOCKET_NUMBER`), the `regulator_code` of the authority that opened it (1 to 16 characters), and the `response_due_at` deadline by which both filings must be on record, which must be strictly after the logical clock at creation — a deadline at or before the clock is a malformed request answering `ERR_INVALID_REQUEST`, decided at ladder step 3 and therefore ahead of the `complaint_id` lookup. The docket opens in state `RECEIVED` with `filed_late` false, both `technical_packet_filed_at` and `resolution_report_filed_at` null, both `technical_evidence_ref` and `resolution_report_ref` null, and `closure_note` and `closed_at` null. Dockets are readable individually and listable with filters on `complaint_id` and `state`.

Answering a docket requires two independent filings, each with its own precondition and its own recorded evidence. A filing names its `filing_type` — either `TECHNICAL_PACKET` or `RESOLUTION_REPORT` — an `evidence_ref` recorded against that branch, and a `summary`. A `TECHNICAL_PACKET` filing may only be made when the label disputed by the docket's complaint still stands up technically: its `attestation_id` must be non-null *and* its `substantiation_status` must be `SUBSTANTIATED`, or the filing is rejected with `ERR_LABEL_NOT_SUBSTANTIATED_FOR_FILING`. This is precisely the case that the invalidation cascade of §3.3 creates — once hop 4 has revoked the pinned attestation, the technical packet cannot be filed until a replacement attestation re-substantiates the label. A `TECHNICAL_PACKET` filing records `technical_evidence_ref` from the supplied `evidence_ref` and `technical_packet_filed_at` as the logical clock. A `RESOLUTION_REPORT` filing may only be made when the docket's complaint has reached one of `UPHELD`, `DISMISSED` or `WITHDRAWN`, or it is rejected with `ERR_COMPLAINT_NOT_TERMINAL`; it records `resolution_report_ref` from the supplied `evidence_ref` and `resolution_report_filed_at` as the logical clock.

The two branches are a fork that joins. Whichever filing arrives first moves the docket `RECEIVED → EVIDENCE_ASSEMBLY`. The second filing must name the branch whose timestamp is still null and must satisfy that branch's own precondition; naming a branch already filed, or filing at all against a docket whose state is `RESPONSE_COMPLETE` or `CLOSED`, answers `ERR_INQUIRY_INVALID_STATE`. The second filing records its branch's reference and timestamp and then joins: because both `technical_packet_filed_at` and `resolution_report_filed_at` are now non-null, the docket moves `EVIDENCE_ASSEMBLY → RESPONSE_COMPLETE`. At that join the docket's `filed_late` is set to true when the later of the two filing timestamps is strictly after `response_due_at`, and to false otherwise.

Closing the docket carries a `closure_note` and is only admissible from `RESPONSE_COMPLETE`; a docket still in `RECEIVED` or `EVIDENCE_ASSEMBLY` answers `ERR_INQUIRY_FILINGS_INCOMPLETE`. Closure sets `state` to `CLOSED`, its terminal state, records `closed_at` as the logical clock, and stores the supplied `closure_note`.

## 4. Endpoint Definitions

Operations that bring a new resource into existence return `201 Created`. Operations that modify an existing resource — including every action that drives a state transition, and the clock-repositioning capability — return `200 OK`. All reads return `200 OK`. In the table below, "Any" means all seven roles are authorised.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Reposition the server's logical UTC clock | Any |
| POST | `/service-plans` | Create a service plan | ComplianceOfficer |
| GET | `/service-plans/{id}` | Read one service plan, including its current version | Any |
| PATCH | `/service-plans/{id}` | Amend disclosed plan attributes | ComplianceOfficer |
| POST | `/service-plans/{id}/fee-line-items` | Add an itemised fee line to a plan | ComplianceOfficer |
| GET | `/service-plans/{id}/fee-line-items` | List a plan's fee line items | Any |
| POST | `/methodology-documents` | Draft a test methodology document | NetworkEngineer |
| GET | `/methodology-documents/{id}` | Read one methodology document | Any |
| POST | `/methodology-documents/{id}/publish` | Publish a methodology document | ComplianceOfficer |
| POST | `/measurement-probes` | Register a measurement probe panel | NetworkEngineer |
| GET | `/measurement-probes/{id}` | Read one measurement probe | Any |
| POST | `/test-runs` | Record a completed measurement window and its samples | NetworkEngineer |
| GET | `/test-runs/{id}` | Read one measurement run | Any |
| GET | `/test-runs` | List measurement runs | Any |
| POST | `/test-runs/{id}/invalidate` | Withdraw a measurement run from the evidence pool | NetworkEngineer |
| POST | `/performance-attestations` | Compute a typical-speed attestation under one metric variant | NetworkEngineer |
| POST | `/performance-attestations/{id}/certify` | Certify an attestation so labels may cite it | ComplianceOfficer |
| GET | `/performance-attestations/{id}` | Read one attestation | Any |
| GET | `/performance-attestations` | List attestations | Any |
| POST | `/label-versions` | Draft a consumer label for a plan | ComplianceOfficer |
| GET | `/label-versions/{id}` | Read one label version | Any |
| GET | `/label-versions` | List label versions | Any |
| POST | `/label-versions/{id}/publish` | Publish a drafted label | ComplianceOfficer |
| POST | `/label-versions/{id}/withdraw` | Withdraw a published label and restore its predecessor | ComplianceOfficer |
| POST | `/label-versions/{id}/translations` | Add a locale translation to a drafted label | LocalizationSpecialist |
| GET | `/label-versions/{id}/translations` | List a label's translations | Any |
| POST | `/label-versions/{id}/translations/{translationId}/verify` | Verify a translation | LocalizationSpecialist |
| GET | `/label-versions/{id}/disclosures` | List the disclosures recorded against one label version | Any |
| POST | `/subscriber-accounts` | Enrol a subscriber on a plan | RetailAgent |
| GET | `/subscriber-accounts/{id}` | Read one subscriber account | Any |
| GET | `/subscriber-accounts` | List subscriber accounts | ComplianceOfficer, ComplaintAnalyst, RegulatoryLiaison, RetailAgent |
| POST | `/subscriber-accounts/{id}/label-disclosures` | Record that the label in effect was displayed to the subscriber | RetailAgent, Subscriber |
| GET | `/subscriber-accounts/{id}/label-disclosures` | List an account's disclosure history | ComplianceOfficer, ComplaintAnalyst, RegulatoryLiaison, RetailAgent, Subscriber |
| POST | `/complaints` | Intake a consumer complaint against a published label | Subscriber, ComplaintAnalyst |
| GET | `/complaints/{id}` | Read one complaint | ComplianceOfficer, NetworkEngineer, ComplaintAnalyst, RegulatoryLiaison, RetailAgent, Subscriber |
| GET | `/complaints` | List complaints | ComplianceOfficer, NetworkEngineer, ComplaintAnalyst, RegulatoryLiaison, RetailAgent, Subscriber |
| POST | `/complaints/{id}/triage` | Triage an intaken complaint and start its response clock | ComplaintAnalyst |
| POST | `/complaints/{id}/investigate` | Open or resume the investigation | ComplaintAnalyst |
| POST | `/complaints/{id}/request-info` | Pause the investigation pending subscriber information | ComplaintAnalyst |
| POST | `/complaints/{id}/resolve` | Resolve the complaint as upheld or dismissed | ComplaintAnalyst |
| POST | `/complaints/{id}/reopen` | Reopen a dismissed complaint | ComplaintAnalyst |
| POST | `/complaints/{id}/withdraw` | Withdraw the complaint | Subscriber |
| GET | `/complaints/{id}/remediation-credits` | List the credits issued for one complaint | ComplianceOfficer, ComplaintAnalyst, RegulatoryLiaison, RetailAgent, Subscriber |
| GET | `/remediation-credits/{id}` | Read one remediation credit | ComplianceOfficer, ComplaintAnalyst, RegulatoryLiaison, RetailAgent |
| POST | `/remediation-credits/{id}/void` | Void an issued credit and reverse its balance effect | ComplianceOfficer |
| POST | `/regulator-inquiries` | Open a regulator docket against a complaint | RegulatoryLiaison |
| GET | `/regulator-inquiries/{id}` | Read one regulator docket | ComplianceOfficer, NetworkEngineer, ComplaintAnalyst, RegulatoryLiaison |
| GET | `/regulator-inquiries` | List regulator dockets | ComplianceOfficer, NetworkEngineer, ComplaintAnalyst, RegulatoryLiaison |
| POST | `/regulator-inquiries/{id}/filings` | File the technical packet or the resolution report | RegulatoryLiaison |
| POST | `/regulator-inquiries/{id}/close` | Close a docket whose two filings are on record | RegulatoryLiaison |
| POST | `/plan-change-notices` | Send a plan-change or price-increase notice | RetailAgent |
| GET | `/plan-change-notices/{id}` | Read one notice | ComplianceOfficer, ComplaintAnalyst, RegulatoryLiaison, RetailAgent, Subscriber |
| GET | `/plan-change-notices` | List notices | ComplianceOfficer, ComplaintAnalyst, RegulatoryLiaison, RetailAgent, Subscriber |
| POST | `/plan-change-notices/{id}/acknowledge` | Record the subscriber's acknowledgement | Subscriber |
| POST | `/plan-change-notices/{id}/effect` | Apply an acknowledged notice once its effective date has arrived | RetailAgent |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_ACCOUNT_SCOPE_VIOLATION` | 403 |
| `ERR_SOD_SELF_PUBLISH` | 403 |
| `ERR_SOD_SELF_REVIEW` | 403 |
| `ERR_STALE_PLAN_VERSION` | 412 |
| `ERR_SERVICE_PLAN_NOT_FOUND` | 404 |
| `ERR_METHODOLOGY_DOCUMENT_NOT_FOUND` | 404 |
| `ERR_MEASUREMENT_PROBE_NOT_FOUND` | 404 |
| `ERR_TEST_RUN_NOT_FOUND` | 404 |
| `ERR_ATTESTATION_NOT_FOUND` | 404 |
| `ERR_LABEL_VERSION_NOT_FOUND` | 404 |
| `ERR_TRANSLATION_NOT_FOUND` | 404 |
| `ERR_SUBSCRIBER_ACCOUNT_NOT_FOUND` | 404 |
| `ERR_COMPLAINT_NOT_FOUND` | 404 |
| `ERR_REMEDIATION_CREDIT_NOT_FOUND` | 404 |
| `ERR_REGULATOR_INQUIRY_NOT_FOUND` | 404 |
| `ERR_PLAN_CHANGE_NOTICE_NOT_FOUND` | 404 |
| `ERR_LABEL_INVALID_STATE` | 409 |
| `ERR_ATTESTATION_INVALID_STATE` | 409 |
| `ERR_TEST_RUN_ALREADY_INVALIDATED` | 409 |
| `ERR_METHODOLOGY_ALREADY_PUBLISHED` | 409 |
| `ERR_TRANSLATION_INVALID_STATE` | 409 |
| `ERR_COMPLAINT_INVALID_STATE` | 409 |
| `ERR_CREDIT_ALREADY_VOIDED` | 409 |
| `ERR_INQUIRY_INVALID_STATE` | 409 |
| `ERR_INQUIRY_FILINGS_INCOMPLETE` | 409 |
| `ERR_NOTICE_INVALID_STATE` | 409 |
| `ERR_ACCOUNT_CHANGE_ALREADY_PENDING` | 409 |
| `ERR_PLAN_POSTURE_FROZEN` | 409 |
| `ERR_PLAN_POSTURE_RESTRICTED` | 409 |
| `ERR_ACCESSIBILITY_FORMAT_UNSUPPORTED` | 422 |
| `ERR_MEASUREMENT_WINDOW_FUTURE` | 422 |
| `ERR_NOTICE_PERIOD_TOO_SHORT` | 422 |
| `ERR_LABEL_EFFECTIVE_NOT_AFTER_PUBLISHED` | 422 |
| `ERR_NOTICE_NOT_DUE` | 422 |
| `ERR_DUPLICATE_PLAN_CODE` | 409 |
| `ERR_DUPLICATE_DOCKET_NUMBER` | 409 |
| `ERR_LABEL_WINDOW_OVERLAP` | 409 |
| `ERR_PROBE_COOLDOWN_CONFLICT` | 409 |
| `ERR_RUN_DURATION_EXCEEDED` | 422 |
| `ERR_SAMPLE_OUTSIDE_WINDOW` | 422 |
| `ERR_NO_ELIGIBLE_TEST_RUNS` | 409 |
| `ERR_INSUFFICIENT_SAMPLES` | 409 |
| `ERR_METHODOLOGY_NOT_PUBLISHED` | 409 |
| `ERR_ATTESTATION_NOT_CERTIFIED` | 409 |
| `ERR_TRANSLATION_COVERAGE_INCOMPLETE` | 409 |
| `ERR_FEE_ITEMIZATION_INCOMPLETE` | 409 |
| `ERR_TRANSLATION_NOT_AVAILABLE` | 409 |
| `ERR_LABEL_NOT_EFFECTIVE_FOR_SERVICE_DATE` | 409 |
| `ERR_COMPLAINT_NOT_TERMINAL` | 409 |
| `ERR_LABEL_NOT_SUBSTANTIATED_FOR_FILING` | 409 |
| `ERR_SHORTFALL_NOT_SUBSTANTIATED` | 422 |
| `ERR_SUBSTANTIATION_MARGIN_NOT_MET` | 422 |
| `ERR_REOPEN_WINDOW_EXPIRED` | 409 |
