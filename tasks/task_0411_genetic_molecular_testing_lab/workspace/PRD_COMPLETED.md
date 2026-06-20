# Genetic & Molecular Testing Lab API — Product Requirements Document

## 1. Introduction

This document specifies the requirements for the Genetic & Molecular Testing Lab API, the operational backbone of a clinical laboratory that offers gene-panel sequencing in the spirit of large reference labs. The platform must orchestrate the full arc of a molecular test: a clinician orders a published panel for a patient, intake builds a requisition and captures informed consent, accessioning receives and screens a physical specimen, the lab sequences the sample and classifies the variants it finds, and finally a laboratory director signs out a report that becomes part of the patient's record. Threaded through this clinical pipeline is a parallel revenue-cycle process — prior authorization with the payer, denial-to-self-pay conversion, and collection of the patient's share — that advances on its own schedule and only ever couples back to the clinical track at the moment of sign-out.

The domain carries genuine regulatory weight, and the API is expected to encode it. Two scientists must never be the same person across the classify/sign-out boundary, consent must be on file before a consent-required panel is touched, variants of uncertain significance cannot leave the building without a genetic-counseling referral, and incidental "secondary" findings are disclosed only under a policy that depends on the patient's consent election and, for minors, on the severity and reportability of the finding. Several figures are money, several are timestamps governed by a deterministic test clock, and a handful of derived figures (panel gene counts, two distinct patient-responsibility estimates, pathogenicity risk indices) must be recomputed faithfully whenever their inputs change.

The remainder of this document is organized into global, system-wide rules (Section 2), the business workflows and their interlocking rules (Section 3), a consolidated endpoint table (Section 4), and the error catalogue (Section 5). Field names, state values, and numeric thresholds are introduced where they make business sense; an implementer is expected to read Section 3 as the authoritative narrative of behavior and to consult Section 4 only for the HTTP surface.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API. The API is mounted under the `/lab` prefix.

### 2.1. User and Role-Based Access Control

Every request to the API must be authenticated through two mandatory HTTP headers. `X-User-ID` identifies the acting user, and `X-User-Role` declares the operational capacity in which they are acting. If either header is missing, or if `X-User-Role` is not one of the recognized role names, the request is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT` (HTTP 401). This applies to every endpoint, including the test-driving clock endpoints under `/lab/_clock`, which still require valid headers even though they are administrative.

The system recognizes exactly six roles: `LabDirector`, `LabIntake`, `AccessioningTech`, `MolecularTechnologist`, `BillingSpecialist`, and `GeneticCounselor`. Each operation is permitted only for the roles enumerated for it in Section 4; if a caller's role is not authorized for the requested operation, the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403). All read (GET) endpoints are available to all six roles.

Every role in this system carries an **opaque** identity. That is, for each of the six roles, `X-User-ID` is an operator identifier that is not tied to any persisted entity, and the server never compares it to any entity's `id`. The server does, however, record the acting `X-User-ID` where a workflow demands an audit anchor: when a `MolecularTechnologist` classifies a variant, their `X-User-ID` is written to that variant's `classified_by_user_id`; when a `LabDirector` signs out a report, their `X-User-ID` is written to that report's `signed_out_by_user_id`. These recorded values exist to enforce the two-person-integrity rule described in Section 3, not to establish resource ownership.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps how many items are returned; it defaults to 10, with a minimum of 1 and a maximum of 100. A supplied `limit` outside that range is not rejected but silently clamped to the nearest bound (values below 1 become 1, values above 100 become 100). The `offset` parameter is the number of leading items to skip and defaults to 0; a negative `offset` is likewise clamped to 0. A `limit` or `offset` that is present but not an integer is rejected with `ERR_INVALID_REQUEST` (HTTP 422).

Unless a specific endpoint states otherwise, list results are ordered by the resource's creation timestamp (`created_at`) in ascending order. Every list response carries the pagination fields `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the envelope.

### 2.4. Common Resource Properties and the Deterministic Clock

Most resources in this system are full first-class entities and carry a standard set of system-managed fields: an `id` that is a server-minted UUID with no type prefix; a `created_at` ISO 8601 UTC timestamp with three fractional digits recording first creation; an `updated_at` ISO 8601 UTC timestamp, likewise with three fractional digits, refreshed on every mutation; and a `version` integer that begins at 1 and increments by one on every mutation of the resource. These four fields apply to genes, panels, panel-gene memberships, providers, test orders, requisitions, consents, specimens, variants, reports, billing records, sequencers, sequencer runs, genetic-counselor profiles, and counselor referrals.

The lab clock is the sole exception. The `LabClock` is a singleton holding a single field, `current_utc`, the deterministic system time. It is **not** a common-fields resource: it carries neither `updated_at` nor `version`, and is read and written only through the clock endpoints. On first boot the clock is initialized to `2026-01-01T00:00:00.000Z`, and it advances only when an operator sets it explicitly by supplying the new instant as `to_iso8601`, which becomes the clock's `current_utc`. All server-stamped timestamps that the business rules reference — most importantly a specimen's accessioning receipt time and the patient-age computation at sign-out — read from this clock rather than wall-clock time.

### 2.5. Hierarchical Retrieval and Cascade Consistency

Many resources are addressed through nested paths that embed more than one identifier — for example, a specimen lives beneath its order, and a sequencer run beneath its instrument. For any such request, the server validates the path identifiers from left to right and rejects the request at the **first** identifier that does not resolve, returning that identifier's specific not-found error (for instance, an unknown order id yields `ERR_ORDER_NOT_FOUND` before the nested specimen is even consulted). The not-found errors are resource-specific: `ERR_ORDER_NOT_FOUND`, `ERR_PANEL_NOT_FOUND`, `ERR_GENE_NOT_FOUND`, `ERR_PROVIDER_NOT_FOUND`, `ERR_REQUISITION_NOT_FOUND`, `ERR_CONSENT_NOT_FOUND`, `ERR_SPECIMEN_NOT_FOUND`, `ERR_VARIANT_NOT_FOUND`, `ERR_REPORT_NOT_FOUND`, `ERR_REFERRAL_NOT_FOUND`, `ERR_PANEL_GENE_NOT_FOUND`, `ERR_SEQUENCER_NOT_FOUND`, `ERR_RUN_NOT_FOUND`, and `ERR_COUNSELOR_NOT_FOUND`, with `ERR_NOT_FOUND` as a generic fallback.

Several operations mutate more than one resource in a single call. Whenever the server changes any resource as a side effect — whether the directly targeted resource or a cascaded parent or child — it refreshes that resource's `updated_at` and increments its `version`. These automatic, server-initiated transitions do not require a separate client request against the affected resource; the cascades are spelled out in the Section 3 workflows that trigger them.

### 2.6. Monetary Values, Precision, and Rounding

All monetary amounts in this system are stored as integer cents — list prices, allowed amounts, collected coinsurance, write-offs, and both patient-responsibility figures. Wherever a calculation produces a fractional cent (for instance, applying a coinsurance rate to a base amount), the result is rounded to whole cents using the **round half up** convention. As detailed in Section 3, rounding for patient responsibility occurs exactly once, at the gross-coinsurance step; all subsequent capping and surcharge arithmetic operates on already-rounded integer cents.

### 2.7. Optimistic Concurrency on Report Amendment

Amending a signed-out report is the one operation guarded by optimistic concurrency control, because an amendment legitimately supersedes a prior report and must not be applied twice against a stale view of the order. The amend operation requires the field `expected_test_order_version` in its request body, carrying the `version` of the parent `TestOrder` that the client last observed. The server compares that value against the order's current `version`; if they differ — for example, because a prior amendment has already advanced the order's `version` and moved the earlier report to its superseded state — the request is rejected with `ERR_STALE_ORDER_VERSION` (HTTP 412), and no successor report is created. This guard is evaluated early, before the amend's business preconditions. No other endpoint accepts a version field, and no other endpoint performs this check.

### 2.8. Validation Ordering

When several checks could fire on a single request, they are evaluated in a fixed priority so that the returned error is deterministic. The order is: first, user-context validity (`ERR_MISSING_OR_INVALID_USER_CONTEXT`); then role authorization (`ERR_FORBIDDEN_ROLE`); then existence of every path identifier, left to right (the resource-specific not-found errors); then, on report amendment only, the optimistic-concurrency version check (`ERR_STALE_ORDER_VERSION`); then whether the target resource is in a state from which the requested transition is defined (the bad-state family: `ERR_ORDER_BAD_PIPELINE_STATE`, `ERR_SPECIMEN_BAD_STATE`, `ERR_REPORT_BAD_STATE`, `ERR_BILLING_BAD_STATE`, `ERR_REFERRAL_BAD_STATE`, and `ERR_RUN_BAD_STATE`); and finally the domain-specific business, safety, fiscal, and temporal constraints described throughout Section 3. Body well-formedness — required fields present, enums in range, integers non-negative, timestamps parseable, and the two interval-ordering checks (a run's end strictly after its start, a slot's end strictly after its start) — surfaces as `ERR_INVALID_REQUEST` (HTTP 422) and is checked as part of that final business layer for any POST or PUT carrying a body. Within the sign-out operation specifically, whose preconditions are unusually dense, the business checks are themselves ordered; that ordering is described where sign-out is narrated in Section 3.

### 2.9. State Enumerations

For precision, the complete set of state strings is collected here; their transitions and the conditions that drive them are narrated in Section 3.

A test order's clinical dimension, `pipeline_status`, takes one of `ORDERED`, `REQUISITIONED`, `ACCESSIONED`, `SEQUENCING`, `CLASSIFIED`, `SIGNED_OUT`, or `CANCELLED`. Its independent financial dimension, `financial_status`, takes one of `PENDING`, `AUTH_REQUESTED`, `AUTH_APPROVED`, `AUTH_DENIED`, `PATIENT_PAY`, or `SETTLED`. A `Billing` record's `status` mirrors and drives that dimension and takes `OPEN`, `AUTH_REQUESTED`, `AUTH_APPROVED`, `AUTH_DENIED`, `PATIENT_PAY`, `SETTLED`, or `REVERSED`. A `Gene` is `ACTIVE` or `RETIRED`; a `Panel` is `DRAFT`, `PUBLISHED`, or `RETIRED`; a `PanelGene` membership is `INCLUDED` or `REMOVED`. A `Requisition` is `PENDING`, `SUBMITTED`, or `VOID`; a `Consent` is `DRAFT`, `SIGNED`, or `REVOKED`; a `Specimen` is `RECEIVED`, `ACCESSIONED`, `QNS_REJECTED`, or `SUPERSEDED`. A `Variant`'s `classification` is one of `UNCLASSIFIED`, `BENIGN`, `LIKELY_BENIGN`, `VUS`, `LIKELY_PATHOGENIC`, `PATHOGENIC`, or `RECLASSIFIED`. A `Report` is `DRAFT`, `SIGNED_OUT`, or `AMENDED`. A `Sequencer` is `ONLINE` or `OFFLINE`, and a `SequencerRun` is `SCHEDULED`, `RUNNING`, `DONE`, or `ABORTED`. A `GeneticCounselorProfile` is `ACTIVE` or `INACTIVE`, and a `CounselorReferral` is `REQUESTED`, `SCHEDULED`, `COMPLETED`, or `CANCELLED`.

## 3. Business Logic & Workflows

### 3.1. Building the Catalog: Genes, Panels, and Memberships

Before any patient testing can occur, a `LabDirector` populates the catalog. A gene is created with its HGNC `symbol` (for example, BRCA1), which must be unique across all gene rows and is compared case-sensitively, and an optional `is_acmg_reportable` flag that defaults to `false` and marks the gene as belonging to the ACMG secondary-findings list. A newly created gene begins in `ACTIVE` `status`. A creation that would duplicate an already-used unique field — here the gene `symbol`, and likewise a provider's `npi`, a sequencer's `instrument_name`, and a counselor's `counselor_name` elsewhere — is rejected with `ERR_INVALID_REQUEST` (HTTP 422).

A panel is created with a display `name`, a `list_price_cents` catalog price that must be a non-negative integer, and an optional `requires_consent` flag that defaults to `true`. A panel begins in `DRAFT` `status` with a `gene_count` of zero. The director assembles the panel by adding genes to it; each addition creates a `PanelGene` membership whose `panel_id` is taken from the URL path and whose `gene_id` is supplied in the body, starting in `INCLUDED` `status`. The panel's `gene_count` is a derived figure equal to the number of `PanelGene` rows for that panel whose `status` is `INCLUDED`; memberships in `REMOVED` status are excluded from the count, and the count is recomputed whenever memberships change. Publishing the panel advances it from `DRAFT` to `PUBLISHED`; orders may be placed only against a panel that has reached `PUBLISHED`. A panel may also be `RETIRED`.

### 3.2. Placing an Order and Building the Requisition

Patient testing begins when a `LabIntake` operator places a test order. Order placement requires the patient's `patient_mrn` (an opaque medical-record number), the patient's `patient_dob` as a `YYYY-MM-DD` date string, the `panel_id` of the ordered panel, and the `ordering_provider_id` of the clinician who placed it. The chosen panel must be in `PUBLISHED` status at order time; an order against a panel not in `PUBLISHED` status is rejected with `ERR_PANEL_NOT_PUBLISHED` (HTTP 409). The provider must have been registered beforehand: a provider carries a unique National Provider Identifier `npi` and a `full_name`, and is created by either `LabIntake` or `LabDirector`.

Upon successful placement the order's `pipeline_status` is `ORDERED` and its `financial_status` is `PENDING`. The order captures an immutable snapshot of the panel's `list_price_cents` into its own `list_price_cents`, and a snapshot of the panel's `requires_consent` flag into `report_required_consent`. The flag `has_reportable_incidental` is initialized to `false`, and the order's `cancel_reason` field (carried on every order representation) is initialized to null, to be populated only by a later cancellation. As a side effect of placement, the server also creates the order's `Billing` record in `OPEN` status, with `allowed_amount_cents` null and both `coinsurance_collected_cents` and `writeoff_cents` initialized to `0`. The two responsibility figures, `estimated_patient_responsibility_cents` and `final_patient_responsibility_cents`, are not yet populated; they are filled in by the billing and sign-out workflows described later.

Intake then attaches a requisition to the order — exactly one requisition per order. Creating it requires a `clinical_indication` (the ICD-like reason for testing) and an `insurance_payer`, which is one of `MEDICARE`, `COMMERCIAL`, or `SELF_PAY`; the new requisition starts in `PENDING` `status`. Submitting the requisition is the event that pushes the clinical pipeline forward: it is permitted only while the order's `pipeline_status` is `ORDERED` (otherwise `ERR_ORDER_BAD_PIPELINE_STATE`) and only when a requisition in `PENDING` status exists (otherwise `ERR_REQUISITION_NOT_FOUND`). Submission moves the requisition from `PENDING` to `SUBMITTED` and advances the order from `ORDERED` to `REQUISITIONED`. Submission also forks the financial track and computes the first responsibility estimate, both described in Section 3.6.

### 3.3. Informed Consent

Consent is managed as its own record beneath the order. A `LabIntake` operator creates a consent with the patient's `incidental_findings_opt_in` election (whether the patient elects to receive ACMG secondary, incidental findings) and the `signed_by_name` of the consenting party — the patient or a legal guardian. A consent begins in `DRAFT` `status`. Signing it advances `DRAFT` to `SIGNED`; revoking it moves a `DRAFT` or `SIGNED` consent to `REVOKED`.

Consent matters at accessioning. When the ordered panel's `requires_consent` was true — that is, when the order's `report_required_consent` snapshot is true — a consent in `SIGNED` status must exist before a specimen can be accessioned; absent one, accessioning is rejected with `ERR_CONSENT_REQUIRED` (HTTP 409). The patient's incidental-findings election recorded here also feeds the disclosure policy applied at sign-out (Section 3.8).

### 3.4. Accessioning a Specimen and the QNS Branch

An `AccessioningTech` registers a physical specimen against the order with its `specimen_type` — one of `BLOOD`, `SALIVA`, or `TISSUE` — its `collected_at` collection timestamp, and its `quantity_ng` DNA yield in nanograms. A registered specimen begins in `RECEIVED` `status`; its `received_at` field is left unset until accessioning, and its `superseded_by_specimen_id` is null.

Accessioning a specimen is the gate into the sequencing pipeline and is permitted only while the order is in `REQUISITIONED` `pipeline_status` (otherwise `ERR_ORDER_BAD_PIPELINE_STATE`) and the specimen is in `RECEIVED` `status` (otherwise `ERR_SPECIMEN_BAD_STATE`); the consent requirement of Section 3.3 is also enforced here. The accession then screens the specimen for quantity-not-sufficient (QNS). Each specimen type has a minimum acceptable yield: blood requires at least 50 nanograms, saliva at least 30 nanograms, and tissue at least 100 nanograms. A specimen is **sufficient** when its `quantity_ng` is greater than or equal to the minimum for its type — the boundary is inclusive, so a yield exactly equal to the minimum passes.

On the sufficient branch, the server stamps `received_at` with the current lab clock value, moves the specimen from `RECEIVED` to `ACCESSIONED`, and advances the order's `pipeline_status` from `REQUISITIONED` to `ACCESSIONED`. If this accession is a replacement for an earlier rejected specimen on the same order, that earlier specimen — which is sitting in `QNS_REJECTED` — is moved to `SUPERSEDED`, and its `superseded_by_specimen_id` is set to the id of the newly accessioned specimen.

On the insufficient branch, the specimen is moved from `RECEIVED` to `QNS_REJECTED` and the order's `pipeline_status` stays at `REQUISITIONED`, awaiting a resubmitted specimen. A QNS rejection is a recorded clinical outcome, not a validation failure: the accession call still succeeds and returns the rejected specimen with its updated status rather than emitting an error. (The `ERR_SPECIMEN_QNS` situation is therefore handled by recording the outcome, not by returning an error.)

### 3.5. Sequencing, Variant Calling, and Classification

Once an order is `ACCESSIONED`, an `AccessioningTech` starts sequencing, which advances the order's `pipeline_status` from `ACCESSIONED` to `SEQUENCING` (permitted only from `ACCESSIONED`, else `ERR_ORDER_BAD_PIPELINE_STATE`).

Physical sequencing is scheduled against instruments. A `LabDirector` registers a `Sequencer` with a unique `instrument_name` and an optional `turnaround_buffer_minutes` that defaults to 60; the instrument begins `ONLINE` and may be `OFFLINE`. An `AccessioningTech` schedules a run on an instrument by supplying the `test_order_id` whose specimen is loaded, a `window_start`, and a `window_end`; the run records its instrument as `sequencer_id` taken from the URL path, begins `SCHEDULED`, and its `window_end` must be strictly after `window_start`. A run may then be started (advancing `SCHEDULED` to `RUNNING`, permitted only from `SCHEDULED`), finished (advancing `RUNNING` to `DONE`, permitted only from `RUNNING`), or aborted (moving a run in `SCHEDULED` or `RUNNING` to `ABORTED`); any state-mismatch on these three yields `ERR_RUN_BAD_STATE`. Starting a run additionally requires the referenced order to be in `SEQUENCING` `pipeline_status`; if it is not, the start is rejected with `ERR_ORDER_BAD_PIPELINE_STATE` (this order-state check is evaluated after the run's own `SCHEDULED`-state check). The scheduling overlap rule for runs is detailed in Section 3.9.

While the order is in `SEQUENCING`, a `MolecularTechnologist` calls variants; calling a variant is permitted only while the order's `pipeline_status` is `SEQUENCING`, and an attempt from any other pipeline state is rejected with `ERR_ORDER_BAD_PIPELINE_STATE` (the bad-state check of Section 2.8, evaluated before the body-level field checks below). Each variant is registered with the `gene_id` of the gene it was called in and an `hgvs` nomenclature string (for example, c.68_69delAG); it starts with `classification` `UNCLASSIFIED` and `classified_by_user_id` null. The gene must either be `INCLUDED` on the order's panel, or — if it is not on the panel — must be an ACMG-reportable gene; a variant whose gene is neither included on the panel nor ACMG-reportable is rejected with `ERR_GENE_NOT_ON_PANEL` (HTTP 409). At call time the server computes the variant's `is_incidental` flag: it is `true` precisely when the variant's gene is **not** on the order's panel gene list **and** the gene is ACMG-reportable, marking it as a secondary finding; otherwise it is `false`.

Classifying a variant assigns it a `classification` value, which must be one of the five ACMG tiers — `BENIGN`, `LIKELY_BENIGN`, `VUS`, `LIKELY_PATHOGENIC`, or `PATHOGENIC` — and never `UNCLASSIFIED` or `RECLASSIFIED`; a value outside the five tiers is rejected with `ERR_INVALID_CLASSIFICATION` (HTTP 422). The first classification moves the variant out of `UNCLASSIFIED` and is permitted only while the order is in `SEQUENCING`. Thereafter a variant may be reclassified to any of the five ACMG tiers (the new value is not restricted to the prior value's neighbors): for example, a variant currently at `VUS` may be moved to `PATHOGENIC`, and a variant currently at `PATHOGENIC` may be moved back to `VUS` — the cycle is symmetric and uses the same classify operation, which accepts any of the five tiers regardless of the current classification — and these reclassifications are permitted while the order is in either `SEQUENCING` or `CLASSIFIED`. Reclassifying a variant on an order that has already reached `CLASSIFIED` does not regress the order; it remains `CLASSIFIED`. Every classification (initial or reclassification) records the acting technologist's `X-User-ID` into the variant's `classified_by_user_id` and recomputes the order's pathogenicity index described in Section 3.10.

Finalizing classification advances the order from `SEQUENCING` to `CLASSIFIED` (permitted only from `SEQUENCING`). It requires that no variant on the order remains `UNCLASSIFIED`; if any does, the request is rejected with `ERR_UNCLASSIFIED_VARIANTS_EXIST` (HTTP 409).

### 3.6. The Financial Track: Prior Auth, Self-Pay, and Collection

The billing dimension runs parallel to the clinical pipeline and is driven through the order's `Billing` record, whose `status` is mirrored onto the order's `financial_status`. When the requisition is submitted (Section 3.2), the financial track forks based on the requisition's `insurance_payer`. If the payer is not `SELF_PAY` — that is, `MEDICARE` or `COMMERCIAL` — a prior-authorization request opens: the billing record advances from `OPEN` to `AUTH_REQUESTED` and the order's `financial_status` becomes `AUTH_REQUESTED`, with the billing record's `allowed_amount_cents` left null until the auth decision. If the payer is `SELF_PAY`, the billing record advances from `OPEN` directly to `PATIENT_PAY`, the order's `financial_status` becomes `PATIENT_PAY`, and the billing record's `allowed_amount_cents` is set equal to the order's `list_price_cents`. In either fork the server then computes the estimate variant of patient responsibility into `estimated_patient_responsibility_cents` (Section 3.7); in the non-`SELF_PAY` fork the base `allowed_amount_cents` is still null at submit, so the estimate is computed with a base of zero cents and `estimated_patient_responsibility_cents` is therefore `0` until the approved auth decision recomputes it against the payer-allowed amount.

A `BillingSpecialist` records the payer's prior-auth decision. The decision body carries a `decision` of either `APPROVED` or `DENIED`, and an `allowed_amount_cents` that is required on approval. The decision is permitted only while the billing record is in `AUTH_REQUESTED` `status` (otherwise `ERR_BILLING_BAD_STATE`). On an approval, the supplied `allowed_amount_cents` must be present and must satisfy: greater than or equal to zero and less than or equal to the order's `list_price_cents`; a missing or out-of-range value is rejected with `ERR_ALLOWED_AMOUNT_INVALID` (HTTP 422). A valid approval stores `allowed_amount_cents` on the billing record, advances the record from `AUTH_REQUESTED` to `AUTH_APPROVED`, sets the order's `financial_status` to `AUTH_APPROVED`, and recomputes `estimated_patient_responsibility_cents`. A denial advances the billing record from `AUTH_REQUESTED` to `AUTH_DENIED` and sets the order's `financial_status` to `AUTH_DENIED`.

When a prior auth has been denied, the specialist may convert the order to self-pay. Conversion is permitted only while the billing record is in `AUTH_DENIED` `status` (otherwise `ERR_BILLING_BAD_STATE`). It writes off the denied payer portion — the current `allowed_amount_cents` is added to `writeoff_cents` — then resets `allowed_amount_cents` to equal the order's `list_price_cents`, advances the billing record from `AUTH_DENIED` to `PATIENT_PAY`, sets the order's `financial_status` to `PATIENT_PAY`, and recomputes `estimated_patient_responsibility_cents`.

Collecting the patient's share is permitted only while the billing record is in `PATIENT_PAY` `status` (otherwise `ERR_BILLING_BAD_STATE`). The collect body carries an `amount_cents` that must exactly equal the amount currently owed: if the report has been signed out, the owed amount is the order's `final_patient_responsibility_cents`; otherwise it is the order's `estimated_patient_responsibility_cents`. A mismatch is rejected with `ERR_COLLECT_AMOUNT_MISMATCH` (HTTP 422). On a matching collection, the `amount_cents` is added to `coinsurance_collected_cents`, the billing record advances from `PATIENT_PAY` to `SETTLED`, and the order's `financial_status` becomes `SETTLED`.

### 3.7. Calculating Patient Responsibility (Two Variants)

Patient responsibility is computed by a single tiered-pricing rule that has two variants writing two different fields. Both variants share the same base and rate. The **base** is the billing record's `allowed_amount_cents` (which, for self-pay or converted orders, has been set equal to the order's `list_price_cents`; for approved-payer orders, is the payer-allowed amount). The **coinsurance rate** is tiered by the requisition's `insurance_payer`: `MEDICARE` carries a rate of twenty percent (0.20), `COMMERCIAL` carries ten percent (0.10), and `SELF_PAY` carries the full one hundred percent (1.00), meaning a self-pay patient owes the entire allowed/list amount. The gross figure is the base multiplied by the rate, rounded half up to whole cents; this is the single rounding step in the whole calculation.

The **estimate variant** writes `estimated_patient_responsibility_cents` and runs during the prior-auth phase — on requisition submit, on an approved auth decision, and on self-pay conversion. It takes the rounded gross and clamps it down to no more than a patient-assistance cap of $500.00 (50,000 cents): the result is the smaller of the gross and 50,000 cents. No incidental surcharge is applied in the estimate, because incidental disclosure is not yet known before sign-out.

The **final variant** writes `final_patient_responsibility_cents` and runs once, at report sign-out. It begins from the same gross-then-cap result (gross clamped to the $500.00 estimate cap), then, if the signed-out report discloses an incidental finding, adds an incidental disclosure/counseling surcharge of $75.00 (7,500 cents); if no incidental is disclosed, it adds nothing. Finally it clamps that sum down to no more than the final patient-assistance cap of $600.00 (60,000 cents), which leaves room for the surcharge. The evaluation order is pinned and must be followed exactly: compute gross (the single rounding), then apply the $500.00 cap, then add the surcharge (final only), then re-clamp to the $600.00 final cap. Because the surcharge can apply, the same order can carry a structurally different final figure than its estimate even though both start from the same base and rate.

### 3.8. Signing Out the Report and the Incidental-Findings Policy

A draft report is created against a `CLASSIFIED` order by either a `LabDirector` or a `MolecularTechnologist` (the only precondition beyond existence and role is that the order is in `CLASSIFIED` `pipeline_status`, else `ERR_ORDER_BAD_PIPELINE_STATE`); it begins in `DRAFT` `status` with `reportable_variant_ids` an empty list, `incidental_disclosed` `false`, and `signed_out_by_user_id` and `amends_report_id` null. There is normally one non-superseded report per order; report creation does not itself enforce that uniqueness or reject a second draft, so the single-report property is maintained by the expected workflow rather than by a creation-time guard.

Signing out a report is the single point where the clinical and financial tracks couple, and it is performed only by a `LabDirector`. Its preconditions are evaluated in this order:

1. **Pipeline state.** The order's `pipeline_status` must be `CLASSIFIED`; otherwise `ERR_ORDER_BAD_PIPELINE_STATE`.
2. **Report state.** The report must be in `DRAFT` `status`; otherwise `ERR_REPORT_BAD_STATE`.
3. **Billing cleared.** The order's `financial_status` must be one of `AUTH_APPROVED`, `PATIENT_PAY`, or `SETTLED`; otherwise the sign-out is rejected with `ERR_BILLING_NOT_CLEARED` (HTTP 402). This is the only place the financial dimension gates the clinical dimension.
4. **Segregation of duties.** The signing director's `X-User-ID` must not equal the `classified_by_user_id` of any variant on the order — the person who classified may not be the person who signs out. A violation is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403).
5. **VUS handling.** No variant on the order may carry classification `VUS` unless a counselor referral with `reason` `VUS_FOLLOWUP` exists for the order in `REQUESTED`, `SCHEDULED`, or `COMPLETED` status. A signed-out attempt with an open `VUS` and no such referral is rejected with `ERR_VUS_REFERRAL_REQUIRED` (HTTP 409).

When every precondition holds, the server selects the reportable variants and decides incidental disclosure, then finalizes. The **reportability selection** considers all variants on the order whose `classification` is neither `UNCLASSIFIED` nor `RECLASSIFIED`, taken in `created_at` ascending order (ties broken by id, used only for stable ordering and never as a value). Primary reportables are the variants where `is_incidental` is false and whose classification is one of `VUS`, `LIKELY_PATHOGENIC`, or `PATHOGENIC`; `BENIGN` and `LIKELY_BENIGN` variants are not placed in the report body. Incidental reportables are variants where `is_incidental` is true, admitted only when the incidental-findings policy below admits them. The report's `reportable_variant_ids` is the primary reportables followed by the admitted incidental reportables, and `incidental_disclosed` is true exactly when at least one incidental reportable was admitted.

The **incidental-findings policy** governs each incidental (secondary-finding) variant whose classification is `LIKELY_PATHOGENIC` or `PATHOGENIC`. First, the patient's age at sign-out is computed as the number of whole years between `patient_dob` and the current lab clock, taking the difference in days divided by 365.2425 and rounding down to a whole number of years (floor). The patient is a minor when that age is strictly less than 18; a patient whose age is exactly 18 is an adult (the boundary is inclusive of adulthood). An incidental finding is admitted if and only if the patient's `incidental_findings_opt_in` is true **and** either the patient is not a minor, or the patient is a minor but the gene is ACMG-reportable and the finding's classification is exactly `PATHOGENIC`. In plain terms: an adult who opted in receives all pathogenic and likely-pathogenic secondary findings; a minor who opted in receives only `PATHOGENIC` ACMG secondary findings, with likely-pathogenic incidentals withheld; and `VUS` incidental findings are never auto-disclosed at any age.

Finalization then proceeds: the report's `status` moves from `DRAFT` to `SIGNED_OUT` and `signed_out_by_user_id` is set to the director's `X-User-ID`; the order's `pipeline_status` advances to `SIGNED_OUT`. If any admitted reportable variant is incidental, the order's `has_reportable_incidental` is set to true. The server then computes the final patient-responsibility figure into `final_patient_responsibility_cents` per Section 3.7. Finally, if the order's `financial_status` was `AUTH_APPROVED` at sign-out, the billing record advances from `AUTH_APPROVED` to `PATIENT_PAY`, the order's `financial_status` becomes `PATIENT_PAY`, and the patient's coinsurance becomes owed (collectible per Section 3.6).

### 3.9. Amending a Signed-Out Report

A signed-out report is non-terminal: it may be amended, which creates a successor report that supersedes it. Amendment is performed by a `LabDirector` and is permitted only while the report is in `SIGNED_OUT` `status` (otherwise `ERR_REPORT_BAD_STATE`). The amend body must carry `expected_test_order_version`, and the optimistic-concurrency guard of Section 2.7 is checked first: a stale value yields `ERR_STALE_ORDER_VERSION`.

On a valid amend, the server creates a successor report whose `amends_report_id` points at the report being amended and whose `status` is `SIGNED_OUT`, with freshly recomputed `reportable_variant_ids` and `incidental_disclosed`. The prior report moves from `SIGNED_OUT` to `AMENDED`, its terminal superseded state. For each variant whose classification differs from what the prior report carried, the variant is archived to `RECLASSIFIED` and then re-set to the new classification value recorded on the successor. The amend increments the order's `version` by one — the very change that causes a second amend still holding the pre-amend `expected_test_order_version` to be rejected as stale.

### 3.10. Pathogenicity Risk Index

Every classify and every classification-complete recomputes a pathogenicity risk index for the order, and reclassification recomputes it again. The index considers all variants on the order whose classification is neither `UNCLASSIFIED` nor `RECLASSIFIED`. Each such variant maps to points by ACMG-style weighting: `BENIGN` is 0 points, `LIKELY_BENIGN` is 1, `VUS` is 2, `LIKELY_PATHOGENIC` is 4, and `PATHOGENIC` is 8. A variant that is incidental (a secondary finding) has its points multiplied by an incidental weight of 2; a non-incidental variant uses its points as-is.

The raw total is the sum, over those variants, of each variant's weighted points, accumulated in `created_at` ascending order (ties broken by id, used only for ordering and never as a value). The raw total is then normalized to a 0-to-100 index against the panel's `gene_count`: the denominator is the larger of the panel's `gene_count` and 1, multiplied by 8 (the maximum per-gene points). The risk index is the raw total divided by that denominator, capped so the ratio cannot exceed 1.0, multiplied by 100, and rounded half up to a whole number — exactly once, after the final multiply. The order of operations is pinned: sum first, then divide, then multiply by 100, then round once (sum-then-round, not round-per-variant).

### 3.11. Genetic-Counselor Referrals and Scheduling

A genetic-counselor profile is registered by a `LabDirector` with a unique `counselor_name`; it begins `ACTIVE` and may be `INACTIVE`. A referral against an order may be requested by a `LabDirector`, a `MolecularTechnologist`, or a `GeneticCounselor`. Requesting it requires the `counselor_id` of the assigned counselor and a `reason` of `PATHOGENIC_RESULT`, `VUS_FOLLOWUP`, `INCIDENTAL_FINDING`, or `PATIENT_REQUEST`; an optional `triggering_variant_id` may name the variant that motivated it. A new referral begins in `REQUESTED` `status` with `slot_start` and `slot_end` null. As noted in Section 3.8, a referral with `reason` `VUS_FOLLOWUP` in `REQUESTED`, `SCHEDULED`, or `COMPLETED` status is what unblocks sign-out of an order carrying a `VUS` variant.

A `GeneticCounselor` schedules a requested referral into a time slot by supplying `slot_start` and `slot_end`; scheduling is permitted only from `REQUESTED` `status` (otherwise `ERR_REFERRAL_BAD_STATE`), and `slot_end` must be strictly after `slot_start` (otherwise `ERR_INVALID_REQUEST`). Scheduling records the slot and moves the referral from `REQUESTED` to `SCHEDULED`. The counselor may then complete a scheduled referral (advancing `SCHEDULED` to `COMPLETED`, permitted only from `SCHEDULED`) or cancel a referral that is in `REQUESTED` or `SCHEDULED` (moving it to `CANCELLED`); a state mismatch on complete or cancel yields `ERR_REFERRAL_BAD_STATE`. The counselor slot-conflict rule is detailed in Section 3.12.

### 3.12. Resource Scheduling: Two Distinct Overlap Geometries

The system schedules against two kinds of finite resource — sequencing instruments and counselors — and the two use deliberately different interval geometries.

**Sequencer runs use a closed interval plus a turnaround buffer.** When a run is scheduled on an instrument, the server rejects it if there is another run on the **same** sequencer, in `SCHEDULED` or `RUNNING` status (runs in `ABORTED` or `DONE` are excluded), whose closed interval `[window_start, window_end]` comes within the instrument's `turnaround_buffer_minutes` of the new run's closed interval. Letting B be the instrument's `turnaround_buffer_minutes`, two runs are clear of each other only if the new run's end plus B is at or before the existing run's start, or the existing run's end plus B is at or before the new run's start; if neither of those holds, they conflict. Because the interval is closed and the comparison is at-or-before rather than strictly-before, two runs that merely touch (the new run starting exactly when the existing one ends) do conflict, and two runs separated by exactly B minutes also conflict. A conflicting run is rejected with `ERR_RUN_WINDOW_CONFLICT` (HTTP 409). Aborting a run frees its window: aborted runs are excluded from this check and may have their time re-scheduled.

**Counselor slots use a half-open interval with no buffer.** When a referral is scheduled, the server rejects it if there is another referral for the **same** `counselor_id`, in `SCHEDULED` status, whose half-open interval `[slot_start, slot_end)` overlaps the new `[slot_start, slot_end)`. Two half-open intervals overlap when the new slot's start is before the existing slot's end and the existing slot's start is before the new slot's end. Because the interval is half-open and there is no buffer, adjacency is allowed: a new slot whose start equals an existing slot's end does **not** conflict. A conflicting slot is rejected with `ERR_COUNSELOR_SLOT_CONFLICT` (HTTP 409). This geometry is intentionally distinct from the sequencer rule above; the two checks live on different resources and must not be conflated.

### 3.13. Cancelling an Order and Its Cascades

A `LabIntake` operator may cancel an order while its `pipeline_status` is any of `ORDERED`, `REQUISITIONED`, `ACCESSIONED`, `SEQUENCING`, or `CLASSIFIED`; an attempt to cancel an order already in a terminal state (`SIGNED_OUT` or `CANCELLED`) is rejected with `ERR_ORDER_NOT_CANCELLABLE` (HTTP 409). Cancellation moves the order's `pipeline_status` to `CANCELLED` and records the supplied `cancel_reason` (optional free text — when omitted it is left null, and when supplied it must be a string). The cancel then cascades, touching only non-terminal children:

- Any requisition in `PENDING` or `SUBMITTED` status is moved to `VOID`.
- If the billing record is in `AUTH_REQUESTED`, `AUTH_APPROVED`, or `PATIENT_PAY`, it is moved to `REVERSED`: the difference of the current `allowed_amount_cents` minus the current `coinsurance_collected_cents`, clamped so it is never negative (a floor of zero), is added to `writeoff_cents`; `coinsurance_collected_cents` is then reset to zero; and the order's `financial_status` becomes `SETTLED`.
- Any counselor referral in `REQUESTED` or `SCHEDULED` status is moved to `CANCELLED`.

Children already in terminal states are left untouched, and each child the cascade mutates has its own `updated_at` refreshed and `version` incremented.

## 4. Endpoint Definitions

Operations that create a new, distinct resource return a `201 Created` status code; operations that modify an existing resource (including state transitions and clock operations) return a `200 OK` status code. All endpoints are mounted under the `/lab` prefix, require the `X-User-ID` and `X-User-Role` headers, and validate path identifiers left-to-right as described in Section 2.5. "All roles" below denotes the six roles `LabDirector`, `LabIntake`, `AccessioningTech`, `MolecularTechnologist`, `BillingSpecialist`, and `GeneticCounselor`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/lab/_clock/set_current_utc` | Set the deterministic lab clock | LabDirector |
| GET | `/lab/_clock` | Read the current lab clock | All roles |
| POST | `/lab/genes` | Create a gene catalog entry | LabDirector |
| GET | `/lab/genes` | List genes | All roles |
| GET | `/lab/genes/{geneId}` | Get one gene | All roles |
| POST | `/lab/panels` | Create a panel (DRAFT) | LabDirector |
| GET | `/lab/panels` | List panels | All roles |
| GET | `/lab/panels/{panelId}` | Get one panel | All roles |
| POST | `/lab/panels/{panelId}/publish` | Publish a DRAFT panel | LabDirector |
| POST | `/lab/panels/{panelId}/panel-genes` | Add a gene to a panel | LabDirector |
| GET | `/lab/panels/{panelId}/panel-genes` | List a panel's gene memberships | All roles |
| GET | `/lab/genes/{geneId}/panel-genes` | List panel memberships for a gene | All roles |
| GET | `/lab/panel-genes/{panelGeneId}` | Get one panel-gene membership | All roles |
| GET | `/lab/panel-genes` | List panel-gene memberships | All roles |
| POST | `/lab/providers` | Register an ordering provider | LabIntake, LabDirector |
| GET | `/lab/providers/{providerId}` | Get one provider | All roles |
| POST | `/lab/test-orders` | Place a test order | LabIntake |
| GET | `/lab/test-orders` | List test orders | All roles |
| GET | `/lab/test-orders/{orderId}` | Get one test order | All roles |
| POST | `/lab/test-orders/{orderId}/cancel` | Cancel an order (cascades) | LabIntake |
| POST | `/lab/test-orders/{orderId}/requisition` | Create the requisition (PENDING) | LabIntake |
| GET | `/lab/test-orders/{orderId}/requisition` | List the requisition(s) for an order | All roles |
| GET | `/lab/requisitions/{requisitionId}` | Get one requisition | All roles |
| GET | `/lab/requisitions` | List requisitions | All roles |
| POST | `/lab/test-orders/{orderId}/requisition/submit` | Submit the requisition; advance order and fork prior-auth | LabIntake |
| POST | `/lab/test-orders/{orderId}/consents` | Create a consent record (DRAFT) | LabIntake |
| GET | `/lab/test-orders/{orderId}/consents` | List consents for an order | All roles |
| GET | `/lab/consents/{consentId}` | Get one consent | All roles |
| GET | `/lab/consents` | List consents | All roles |
| POST | `/lab/test-orders/{orderId}/consents/{consentId}/sign` | Sign a DRAFT consent | LabIntake |
| POST | `/lab/test-orders/{orderId}/consents/{consentId}/revoke` | Revoke a consent | LabIntake |
| POST | `/lab/test-orders/{orderId}/specimens` | Register a received specimen | AccessioningTech |
| GET | `/lab/test-orders/{orderId}/specimens` | List specimens for an order | All roles |
| GET | `/lab/specimens/{specimenId}` | Get one specimen | All roles |
| GET | `/lab/specimens` | List specimens | All roles |
| POST | `/lab/test-orders/{orderId}/specimens/{specimenId}/accession` | Accession a specimen; QNS-screen | AccessioningTech |
| POST | `/lab/test-orders/{orderId}/sequencing/start` | Move an ACCESSIONED order into SEQUENCING | AccessioningTech |
| POST | `/lab/test-orders/{orderId}/variants` | Call a variant | MolecularTechnologist |
| GET | `/lab/test-orders/{orderId}/variants` | List variants for an order | All roles |
| GET | `/lab/variants/{variantId}` | Get one variant | All roles |
| GET | `/lab/variants` | List variants | All roles |
| POST | `/lab/test-orders/{orderId}/variants/{variantId}/classify` | Classify or reclassify a variant | MolecularTechnologist |
| POST | `/lab/test-orders/{orderId}/classification/complete` | Finalize classification | MolecularTechnologist |
| POST | `/lab/test-orders/{orderId}/reports` | Create the DRAFT report | LabDirector, MolecularTechnologist |
| GET | `/lab/test-orders/{orderId}/reports` | List reports for an order | All roles |
| GET | `/lab/reports/{reportId}` | Get one report | All roles |
| GET | `/lab/reports` | List reports | All roles |
| POST | `/lab/test-orders/{orderId}/reports/{reportId}/sign-out` | Sign out a DRAFT report | LabDirector |
| POST | `/lab/test-orders/{orderId}/reports/{reportId}/amend` | Amend a SIGNED_OUT report (OCC) | LabDirector |
| GET | `/lab/test-orders/{orderId}/billing` | List the billing record(s) for an order | All roles |
| GET | `/lab/billings/{billingId}` | Get one billing record | All roles |
| GET | `/lab/billings` | List billing records | All roles |
| POST | `/lab/test-orders/{orderId}/billing/auth-decision` | Record a prior-auth decision | BillingSpecialist |
| POST | `/lab/test-orders/{orderId}/billing/convert-self-pay` | Convert a denied auth to self-pay | BillingSpecialist |
| POST | `/lab/test-orders/{orderId}/billing/collect` | Collect patient responsibility | BillingSpecialist |
| POST | `/lab/sequencers` | Register a sequencer instrument | LabDirector |
| GET | `/lab/sequencers` | List sequencers | All roles |
| GET | `/lab/sequencers/{sequencerId}` | Get one sequencer | All roles |
| POST | `/lab/sequencers/{sequencerId}/runs` | Schedule a sequencing run window | AccessioningTech |
| GET | `/lab/sequencers/{sequencerId}/runs` | List runs on a sequencer | All roles |
| GET | `/lab/sequencer-runs/{runId}` | Get one run | All roles |
| GET | `/lab/sequencer-runs` | List runs | All roles |
| POST | `/lab/sequencers/{sequencerId}/runs/{runId}/start` | Start a scheduled run | AccessioningTech |
| POST | `/lab/sequencers/{sequencerId}/runs/{runId}/finish` | Finish a running run | AccessioningTech |
| POST | `/lab/sequencers/{sequencerId}/runs/{runId}/abort` | Abort a run | AccessioningTech |
| POST | `/lab/counselors` | Register a genetic counselor profile | LabDirector |
| GET | `/lab/counselors` | List genetic counselor profiles | All roles |
| GET | `/lab/counselors/{counselorId}` | Get one counselor profile | All roles |
| POST | `/lab/test-orders/{orderId}/referrals` | Request a genetic-counselor referral | LabDirector, MolecularTechnologist, GeneticCounselor |
| GET | `/lab/test-orders/{orderId}/referrals` | List referrals for an order | All roles |
| GET | `/lab/referrals/{referralId}` | Get one referral | All roles |
| GET | `/lab/referrals` | List referrals | All roles |
| POST | `/lab/test-orders/{orderId}/referrals/{referralId}/schedule` | Schedule a requested referral | GeneticCounselor |
| POST | `/lab/test-orders/{orderId}/referrals/{referralId}/complete` | Complete a scheduled referral | GeneticCounselor |
| POST | `/lab/test-orders/{orderId}/referrals/{referralId}/cancel` | Cancel a referral | GeneticCounselor |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT` | 401 Unauthorized |
| `ERR_FORBIDDEN_ROLE` | 403 Forbidden |
| `ERR_ORDER_NOT_FOUND` | 404 Not Found |
| `ERR_PANEL_NOT_FOUND` | 404 Not Found |
| `ERR_GENE_NOT_FOUND` | 404 Not Found |
| `ERR_PROVIDER_NOT_FOUND` | 404 Not Found |
| `ERR_REQUISITION_NOT_FOUND` | 404 Not Found |
| `ERR_CONSENT_NOT_FOUND` | 404 Not Found |
| `ERR_SPECIMEN_NOT_FOUND` | 404 Not Found |
| `ERR_VARIANT_NOT_FOUND` | 404 Not Found |
| `ERR_REPORT_NOT_FOUND` | 404 Not Found |
| `ERR_REFERRAL_NOT_FOUND` | 404 Not Found |
| `ERR_PANEL_GENE_NOT_FOUND` | 404 Not Found |
| `ERR_SEQUENCER_NOT_FOUND` | 404 Not Found |
| `ERR_RUN_NOT_FOUND` | 404 Not Found |
| `ERR_COUNSELOR_NOT_FOUND` | 404 Not Found |
| `ERR_STALE_ORDER_VERSION` | 412 Precondition Failed |
| `ERR_ORDER_BAD_PIPELINE_STATE` | 409 Conflict |
| `ERR_SPECIMEN_BAD_STATE` | 409 Conflict |
| `ERR_REPORT_BAD_STATE` | 409 Conflict |
| `ERR_BILLING_BAD_STATE` | 409 Conflict |
| `ERR_REFERRAL_BAD_STATE` | 409 Conflict |
| `ERR_ORDER_NOT_CANCELLABLE` | 409 Conflict |
| `ERR_PANEL_NOT_PUBLISHED` | 409 Conflict |
| `ERR_CONSENT_REQUIRED` | 409 Conflict |
| `ERR_SEGREGATION_OF_DUTIES` | 403 Forbidden |
| `ERR_VUS_REFERRAL_REQUIRED` | 409 Conflict |
| `ERR_UNCLASSIFIED_VARIANTS_EXIST` | 409 Conflict |
| `ERR_INVALID_CLASSIFICATION` | 422 Unprocessable Entity |
| `ERR_ALLOWED_AMOUNT_INVALID` | 422 Unprocessable Entity |
| `ERR_BILLING_NOT_CLEARED` | 402 Payment Required |
| `ERR_COLLECT_AMOUNT_MISMATCH` | 422 Unprocessable Entity |
| `ERR_GENE_NOT_ON_PANEL` | 409 Conflict |
| `ERR_RUN_WINDOW_CONFLICT` | 409 Conflict |
| `ERR_COUNSELOR_SLOT_CONFLICT` | 409 Conflict |
| `ERR_RUN_BAD_STATE` | 409 Conflict |
| `ERR_INVALID_REQUEST` | 422 Unprocessable Entity |
| `ERR_NOT_FOUND` | 404 Not Found |
