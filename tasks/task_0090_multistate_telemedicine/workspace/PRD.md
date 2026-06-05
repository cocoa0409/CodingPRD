# Multistate Telemedicine API — Product Requirements Document

## 1. Introduction

Practicing medicine across state lines turns a single clinical encounter into a regulatory puzzle. A physician may be fully credentialed in their home state yet have no authority to treat a patient who happens to be physically sitting in a neighbouring state at the moment of the visit; a controlled-substance prescription that is routine in person may be barred over an audio-only connection; and the same telehealth visit may be billed to an insurer in one case and to the patient's own pocket in another. The Multistate Telemedicine API exists to make every one of these decisions explicit, auditable, and reproducible.

This platform models the full arc of a virtual encounter: a physician's portfolio of per-state licenses, a patient's intake and the state they attest to being located in, the compliance evaluation that decides whether the visit may legally proceed, the payment routing that follows from whether the patient is insured, the electronic prescriptions written during the visit (including the stricter rules that apply to DEA-scheduled drugs), the insurance claim that may result, and the follow-up that a completed visit generates. Because the central concern of the domain is *compliance*, every gating decision is written to an append-only evaluation log rather than merely returning a yes-or-no answer — the record of *why* a visit was cleared or blocked is itself a first-class product artifact.

A second theme runs throughout: the right to conduct a given visit is not a static role grant but a function of several moving parts at once — which states a physician is licensed in, where the patient is actually located, which modality is used, and how the visit is to be paid for. The sections that follow specify each of these mechanisms precisely, then describe how they compose across the lifecycle of a visit.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply across the entire API.

### 2.1. User and Role-Based Access Control

Every protected interaction with the API is authenticated through two mandatory HTTP headers. Each such request must include `X-User-ID` to identify the acting user and `X-User-Role` to declare their operational capacity. The platform recognizes five roles, spelled exactly as follows: `Anonymous`, `Physician`, `Patient`, `LicensingBoard`, and `ComplianceOfficer`. When a request that requires authentication arrives without both headers present, or carries an `X-User-Role` that is not one of the declared roles, it is rejected with `ERR_UNAUTHENTICATED`. When the headers are well-formed but the role is not permitted to perform the requested operation — or an ownership-bound actor targets a resource it does not own — the request is rejected with `ERR_FORBIDDEN`.

The roles differ in how their identity binds to data. When `X-User-Role` is `Physician`, `X-User-ID` is the `id` of the acting `Physician`; ownership checks on any resource that references a `Physician` compare the resource's physician foreign key to `X-User-ID` — concretely, a `Physician` may act only on a `Visit` whose `physician_id` equals their `X-User-ID`. When `X-User-Role` is `Patient`, `X-User-ID` is the `id` of the acting `Patient`; ownership checks compare a resource's patient foreign key to `X-User-ID`, so a `Patient` may act only on a `Visit` whose `patient_id` equals their `X-User-ID`. When `X-User-Role` is `LicensingBoard`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity: the server accepts it for authentication but does not compare it to any entity's `id`. When `X-User-Role` is `ComplianceOfficer`, `X-User-ID` is likewise an opaque operator identifier not tied to any persisted entity; the server may record the operator's actions on the append-only compliance log but does not compare the identifier to any entity's `id`. When `X-User-Role` is `Anonymous`, the caller is unauthenticated and may only self-register physicians, patients, and payers, read public resources, and drive the clock.

A small set of endpoints is deliberately public and exempt from the authentication requirement: registering a physician, registering a patient, registering a payer, every read (`GET`) endpoint, and setting the clock. All other endpoints require authentication.

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

For endpoints that return lists of resources, pagination is controlled via query parameters. The `limit` parameter specifies the maximum number of items to return; if not provided it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0, with a minimum of 0. A request whose `limit` falls outside the range of 1 to 100 inclusive, or whose `offset` is less than 0, is rejected with `ERR_PAGINATION_INVALID`.

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp (`created_at`) in ascending order.

Paginated list responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties and the Logical Clock

Most resources in this platform carry a standard set of system-managed fields. Specifically, every `Physician`, `StateLicense`, `Patient`, `Visit`, `Prescription`, `Claim`, and `FollowUp` includes:

- `id` — a unique, server-minted identifier formatted as a UUID, with no type prefix.
- `created_at` — an ISO 8601 UTC timestamp with three fractional digits, recorded when the resource is first created.
- `updated_at` — an ISO 8601 UTC timestamp with three fractional digits, refreshed on every mutation of the resource.
- `version` — an integer that begins at creation and increments by one with every mutation of the resource. It supports optimistic concurrency control as described in §2.7.

Three entities are deliberately leaner. A `Payer`, a `ComplianceCheck`, and the `ClockState` carry only an `id` (a server-minted UUID) and a `created_at` timestamp; for these, both `updated_at` and `version` are absent. The `ComplianceCheck` log in particular is append-only — entries are written once and never revised, which is why it needs neither a modification timestamp nor a version counter.

The platform does not read the host machine's wall clock for any time-sensitive decision. Instead it maintains a single logical clock, the `ClockState`, whose `current_utc` field is the platform's authoritative "now." Every recency window, expiry check, follow-up due computation, and lapse decision reads `current_utc`. The clock begins at `1970-01-01T00:00:00.000Z` and is advanced only through the test-driving clock-set capability, which writes a supplied `current_utc` instant.

### 2.5. Nested Resource Retrieval and Reference Validation

Many endpoints address a resource nested under a parent — for example, the prescriptions authored on a particular visit, or the state licenses held by a particular physician. For any such request, the platform validates the identifiers in the path from left to right, and rejects the request with `ERR_NOT_FOUND` at the *first* identifier in the path that does not resolve to an existing resource. After path identifiers are confirmed, any foreign-key identifiers supplied in the request body are validated in turn; an unresolved body reference likewise yields `ERR_NOT_FOUND`. This left-to-right ordering means, for instance, that a request to list a non-existent physician's licenses fails on the physician before the licenses are ever consulted.

### 2.6. Monetary Precision and Rounding

All monetary amounts in this system are expressed as whole integer cents — `list_fee_cents`, `platform_fee_cents`, `patient_cost_cents`, `copay_cents`, `allowed_amount_cents`, `billed_cents`, `allowed_cents`, and `plan_paid_cents` are all integers. Wherever a calculation multiplies a cent amount by a fractional factor, the intermediate product is rounded to the nearest whole cent using the round-half-up convention (a value whose fractional part is exactly one half rounds upward). The specific points at which rounding is applied — and, critically, the *order* in which rounding and summation occur — are described with each calculation in §3, because that order can change a result by a single cent.

### 2.7. Optimistic Concurrency Control on Prescription Authoring

Controlled-substance prescribing is the one place in this platform where a client must prove it is acting on a fresh view of the data. Each `Visit` carries a `prescription_version`, an integer counter that starts at 0 and is bumped by one each time an accepted controlled-substance authoring supersedes a prior prescription on that visit. Authoring a controlled-substance prescription (any `dea_schedule` other than `NONE`) requires the request to carry `expected_visit_prescription_version`, the value of the visit's `prescription_version` that the client last observed. If that supplied value does not equal the target visit's current `prescription_version` — that is, if another accepted authoring has advanced the counter since the client last read it — the request is rejected with `ERR_STALE_PRESCRIPTION_VERSION` at HTTP 412. This prevents a client from overwriting a prescription set it has not actually observed. Authoring a non-controlled prescription (`dea_schedule` equal to `NONE`) does not participate in this check, and no other endpoint takes a version field.

### 2.8. The Suspension Cascade and Append-Only Compliance Logging

The defining integrity rule of this platform is what happens when a state license is pulled out from under work already in progress. When a `LicensingBoard` suspends a `StateLicense`, every clinical artifact whose legality rested on that license must be unwound, in a chain that can run three levels deep. The propagation is described in full in §3.4; the system-wide principle is that such reconciliations are performed automatically by the server, without the client issuing a request against each affected resource, and that each affected resource is independently mutated — its `updated_at` is refreshed and its `version` is incremented as part of the cascade. Reinstating a license never resurrects artifacts that the cascade already terminated; voided work stays voided.

Equally important, every licensure-and-modality compliance evaluation produces a durable `ComplianceCheck` record regardless of outcome. A cleared evaluation, a blocked evaluation, and an officer override all append a row to this log. Because the log is append-only, the history of compliance decisions for a visit is never overwritten, and the *most recent* entry is what governs whether subsequent actions (such as an override) are permitted.

### 2.9. Interstate Compact Licensure Rules

The Interstate Medical Licensure Compact lets a qualified physician obtain expedited licenses in states other than their principal state. The platform encodes this as a constraint on how licenses may be issued. A `StateLicense` may be issued with an `issuance_type` of either `FULL` or `COMPACT_EXPEDITED`. A `COMPACT_EXPEDITED` license may be created only for a `Physician` whose `imlc_eligible` flag is true, and only for a `state_code` that differs from that physician's `home_state_code` — the compact issues expedited licenses in states *other than* the principal state. A request that violates either condition (a non-eligible physician, or an expedited license in the physician's own home state) is rejected with `ERR_COMPACT_INELIGIBLE`.

## 3. Business Logic & Workflows

### 3.1. The Physician Registry and the Licensure Portfolio

A physician is brought onto the platform through self-registration, supplying a `full_name`, an `npi`, and a `home_state_code`, and optionally a `dea_number` and an `imlc_eligible` flag. The `npi` is the ten-digit National Provider Identifier and must consist of exactly ten numeric digits; it must also be unique across all physicians. The `home_state_code` is a two-letter USPS state code naming the physician's principal state of license under the compact. If `dea_number` is omitted it is stored as null, which later prevents the physician from authoring any controlled-substance prescription. If `imlc_eligible` is omitted it defaults to false. A newly registered physician's `status` is `ACTIVE`, and their `active_license_count` begins at 0. Should a physician's `npi` duplicate an existing one, registration is rejected with `ERR_DUPLICATE_RESOURCE`.

A `LicensingBoard` operator builds out a physician's portfolio by issuing per-state licenses against that physician. Each `StateLicense` names the `state_code` it authorizes practice in, an `issuance_type`, an `effective_date` and an `expiration_date`, and optionally a `controlled_substance_authority` flag (defaulting to false) indicating whether this particular state license carries a state controlled-substance registration. It records the owning physician through its `physician_id`. The `effective_date` is the ISO 8601 UTC instant at which the license becomes valid, inclusive; the `expiration_date` is the instant at which it expires, treated as exclusive — the license is invalid at and after that instant. A freshly issued license has `status` `ACTIVE` and a null `suspension_reason`.

The board may not stack overlapping terms for the same physician in the same state. Treating each license's validity as the half-open interval running from its `effective_date` up to but not including its `expiration_date`, a new license for the same `physician_id` and `state_code` is rejected with `ERR_LICENSE_PERIOD_OVERLAP` if its interval overlaps that of any existing non-`REVOKED` license for that same physician and state. Two intervals overlap when the new license's `effective_date` is earlier than the existing license's `expiration_date` and the existing license's `effective_date` is earlier than the new license's `expiration_date`. Adjacency is explicitly allowed: when the new license's `effective_date` equals an existing license's `expiration_date`, the two half-open intervals share only the excluded endpoint and therefore do not overlap, so consecutive non-overlapping terms in the same state are valid.

The physician's `active_license_count` is a derived figure: it is the number of that physician's `StateLicense` rows whose `status` is `ACTIVE`, and it is recomputed every time any of that physician's licenses changes status. A `LicensingBoard` may also deactivate a physician's registry record, which sets the physician's `status` to `DEACTIVATED`.

### 3.2. Requesting a Visit and Determining the Patient's State

Patients self-register with a `full_name`, an `email`, and a `residence_state_code` (a two-letter USPS code), and may name an `insurance_payer_id` linking them to a payer on file; a patient who supplies no payer is treated as cash/uninsured and the field is stored as null. The `email` doubles as the login identity and must be unique across patients; a duplicate is rejected with `ERR_DUPLICATE_RESOURCE`.

A payer is registered with a `name`, a `copay_cents` flat patient copay applied per covered telehealth visit, a `covered_state_codes` list of two-letter USPS codes in which the payer reimburses telehealth visits, an `allowed_amount_cents` contracted ceiling for a standard telehealth visit, and an optional `telehealth_parity` flag (defaulting to false) indicating whether the payer reimburses telehealth at in-person parity rates. Both `copay_cents` and `allowed_amount_cents` must be zero or greater.

A `Patient` requests a telemedicine visit by naming the `physician_id` they wish to see and their own `patient_id`, the `modality` (`VIDEO` or `AUDIO_ONLY`), the `scheduled_at` instant, the `determined_state_code`, and the `list_fee_cents` for this visit type, optionally including a `platform_fee_cents`. The single most important field here is `determined_state_code`: it is the two-letter USPS code of the state in which the *patient is physically located at visit time*, as attested at intake. This — and not the patient's residence — governs every downstream compliance decision. The `list_fee_cents` is the platform's list (rack) clinical fee and must be strictly greater than zero; the `platform_fee_cents` is an additional technology/service fee that defaults to 0 when omitted, must be zero or greater, and is consulted only by the self-pay cost path. A newly requested visit has `status` `REQUESTED`, a `prescription_version` of 0, and a null `routing` and `patient_cost_cents`.

The platform protects a physician's calendar with a buffer rule. Treating each visit as a point on the timeline at its `scheduled_at`, a new visit conflicts with any existing non-terminal visit for the same `physician_id` — that is, any visit whose `status` is not `CANCELLED`, `VOIDED`, or `COMPLETED` — when the absolute difference between the two `scheduled_at` instants is strictly less than thirty minutes. The thirty-minute buffer is an exclusive boundary: a gap of exactly thirty minutes does not conflict, because the two slots merely abut. A conflicting request is rejected with `ERR_VISIT_SLOT_CONFLICT`. A `Patient` may cancel a visit they own while it is still `REQUESTED` or once it is `COMPLIANCE_CLEARED`, moving it to `CANCELLED`; cancellation has no further side effects.

### 3.3. Running Compliance: Licensure and Modality Gating

Before a visit may proceed, the conducting `Physician` runs the compliance evaluation on it. This is permitted only when the visit is `REQUESTED` and the physician's own `status` is `ACTIVE`. The evaluation answers a single question: does this physician hold a governing license to see this patient in the patient's determined state, by an acceptable modality?

Selecting the governing license proceeds as follows. The candidate set is every `StateLicense` belonging to the visit's physician (`physician_id` matching) whose `state_code` equals the visit's `determined_state_code`, whose `status` is `ACTIVE`, whose `effective_date` is at or before the logical clock's `current_utc`, and whose `expiration_date` is strictly after `current_utc` (the upper bound is exclusive, so a license is treated as expired purely by the clock at and after its expiration instant, independently of its stored status). If at least one candidate qualifies, they are ranked to choose a single governing license: licenses with `issuance_type` of `FULL` are preferred over those of `COMPACT_EXPEDITED`; among equally preferred candidates, the one with the latest `effective_date` wins; and if a tie remains, the one with the earliest `created_at` is the deterministic final choice. The first candidate under that ordering becomes the governing license.

When a governing license is found and the modality rule passes, the evaluation outcome is `CLEARED`: the visit transitions from `REQUESTED` to `COMPLIANCE_CLEARED`, and a `ComplianceCheck` is appended recording the visit through its `visit_id`, an `outcome` of `CLEARED`, a `matched_license_id` set to the selected license's `id`, and a `reason_code` of `LICENSE_MATCH`.

The evaluation can block for two distinct reasons, each recorded but neither advancing the visit. First, the modality rule: an `AUDIO_ONLY` visit cannot be compliance-cleared on this platform — audio-only is not a permitted modality for an initial cleared visit. When the visit's `modality` is `AUDIO_ONLY`, the outcome is `BLOCKED` with a `reason_code` of `AUDIO_ONLY_NOT_PERMITTED`, and the request is rejected with `ERR_MODALITY_NOT_PERMITTED`. Second, the licensure rule: when no candidate license qualifies, the outcome is `BLOCKED` with a null `matched_license_id`, and the request is rejected with `ERR_NO_LICENSE_IN_STATE`. The recorded `reason_code` distinguishes the two licensure sub-cases — `LICENSE_NOT_ACTIVE` when a license for that physician and state exists but is not `ACTIVE` (for example, suspended or revoked), and `NO_LICENSE_IN_STATE` when there is no matching physician-and-state license at all — even though both surface the same `ERR_NO_LICENSE_IN_STATE` error. A blocked evaluation appends its `ComplianceCheck` and returns the error; it does not transition the visit.

A `ComplianceOfficer` provides the escape hatch. The officer may override a recorded block, but only on a visit still in `REQUESTED` status and only when the *most recent* `ComplianceCheck` for that visit has an `outcome` of `BLOCKED` — an override may follow only a recorded block. Overriding appends a `ComplianceCheck` with an `outcome` of `OVERRIDDEN`, a null `matched_license_id`, and a `reason_code` of `OFFICER_OVERRIDE`, and advances the visit from `REQUESTED` to `COMPLIANCE_CLEARED`. The officer override and the physician's clean run are sibling paths to the same `COMPLIANCE_CLEARED` state, differing only in actor and in the reason recorded on the log.

### 3.4. License Suspension and the Three-Hop Cascade

A `LicensingBoard` may suspend, reinstate, or revoke a license, and the consequences of suspension reach deep into the visit graph. Suspension is permitted only on a license that is currently `ACTIVE`; it captures the supplied `suspension_reason`, moves the license to `SUSPENDED`, and decrements the physician's `active_license_count` by one (recomputed as the count of that physician's `ACTIVE` licenses). It then sets off a cascade.

The first hop targets visits. Every `Visit` currently in `COMPLIANCE_CLEARED` whose clearing `ComplianceCheck` has a `matched_license_id` equal to the suspended license transitions from `COMPLIANCE_CLEARED` to `VOIDED`, because its compliance clearance no longer rests on a valid license. The cascade also reaches visits that had already advanced past clearance on the strength of that same license: an `APPROVED_SELF_PAY` visit governed by the suspended license transitions to `VOIDED`, and an `APPROVED_INSURANCE` visit governed by it likewise transitions to `VOIDED`.

The second hop follows each voided visit down to its prescriptions. As part of a visit's transition to `VOIDED`, every `Prescription` on that visit (matched by `visit_id`) whose `status` is `ACTIVE` transitions from `ACTIVE` to `VOIDED`. Prescriptions already in a terminal state — `SUPERSEDED` in particular — are not re-touched.

The third hop applies only on the insurance fork. When the visit being voided is an `APPROVED_INSURANCE` visit, every `Claim` on that visit (matched by `visit_id`) whose `status` is `SUBMITTED` or `ADJUDICATED` transitions to `REVERSED`. A self-pay voided visit carries no claim, because none was ever created on the self-pay branch, so there is nothing to reverse there. Taken together the chain runs license → visit → prescription, with the claim reversal hanging off the insurance visit's void as a parallel consequence.

Reinstatement reverses a suspension going forward but does not reach back into the cascade. A `SUSPENDED` license may be reinstated only while the logical clock's `current_utc` is still earlier than the license's `expiration_date` — a license that expired during its suspension cannot be reinstated. Reinstatement clears the `suspension_reason` back to null, returns the license to `ACTIVE`, and increments the physician's `active_license_count` by one. Crucially, it does *not* revive any visit or prescription the suspension cascade already voided; those remain terminal.

Revocation is the terminal disposition. Revoking an `ACTIVE` license moves it to `REVOKED` and decrements the physician's `active_license_count` by one. Revoking a `SUSPENDED` license also moves it to `REVOKED` but makes no change to `active_license_count`, since a suspended license was already excluded from the count. Any transition requested from a license state that does not define it — for instance suspending an already-suspended license, or reinstating one that is not suspended — is rejected with `ERR_INVALID_STATE`.

### 3.5. Approval, Payment Routing, and the Patient's Cost

Once a visit is `COMPLIANCE_CLEARED`, its conducting `Physician` approves it, and approval forks based purely on whether the patient is insured. Routing does not re-check state coverage at this point; the determined-state coverage question is settled later, on the claim. When the patient on the visit carries insurance — their `insurance_payer_id` is not null — approval routes to insurance: the visit moves from `COMPLIANCE_CLEARED` to `APPROVED_INSURANCE`, its `routing` is set to `INSURANCE`, and its `patient_cost_cents` is computed by the insurance cost path described below. When the patient carries no insurance — `insurance_payer_id` is null — approval routes to self-pay: the visit moves to `APPROVED_SELF_PAY`, its `routing` is set to `SELF_PAY`, and `patient_cost_cents` is computed by the self-pay path. These two forks are the branch point of the visit lifecycle and carry deliberately different side effects.

Under the **insurance** cost path, the platform first computes the recognized amount as the smaller of the visit's `list_fee_cents` and the payer's `allowed_amount_cents`. If the payer offers telehealth parity (`telehealth_parity` is true), the patient owes exactly the payer's `copay_cents`. If the payer does not offer parity, the patient additionally absorbs the parity shortfall: the shortfall is the visit's `list_fee_cents` minus that recognized amount, but never less than zero, and the patient's cost is the `copay_cents` plus that shortfall.

Under the **self-pay** cost path the payer is ignored entirely, and the platform applies a self-pay discount factor of 0.80 (an 80 percent rate, i.e. a twenty-percent discount) to each fee component separately. The order of operations is pinned and matters: the clinical share is the visit's `list_fee_cents` multiplied by 0.80 and then rounded half-up to a whole cent; the platform share is the visit's `platform_fee_cents` multiplied by 0.80 and then rounded half-up to a whole cent; and the patient's cost is the sum of those two already-rounded shares. Each discounted component is rounded *before* the two are added together — rounding each component first and summing afterward can differ by a cent from discounting a combined total, and the per-component-then-sum order is the one this platform uses.

Only the insurance fork creates downstream billing. As a cascade of insurance approval, the platform creates a `Claim` against the visit, recording the visit through `visit_id`, the payer copied from the patient as `payer_id`, and `billed_cents` set to the visit's `list_fee_cents`, with `status` `SUBMITTED`. The platform immediately runs the claim adjudication math (described in §3.6) to pre-populate the claim's `allowed_cents` and `plan_paid_cents`. The final coverage decision, however, is not made here — it is made at the explicit adjudication step. The self-pay fork creates no claim at all.

### 3.6. Claim Adjudication and Coverage

A submitted claim is adjudicated by a `ComplianceOfficer`, and this is where the patient's determined state finally meets the payer's coverage map. Adjudication is permitted only on a claim still in `SUBMITTED` status. If the payer's `covered_state_codes` list contains the source visit's `determined_state_code`, the claim is confirmed: it transitions from `SUBMITTED` to `ADJUDICATED`, and its `allowed_cents` and `plan_paid_cents` are recomputed by the adjudication math. If the payer's `covered_state_codes` does *not* contain the determined state, the claim is denied: it transitions from `SUBMITTED` to `DENIED`, and both `allowed_cents` and `plan_paid_cents` are set to zero.

The adjudication math itself works from the claim and its payer. The allowed amount, `allowed_cents`, is the smaller of the claim's `billed_cents` and the payer's `allowed_amount_cents`. The plan's payment then depends on parity. If the payer offers telehealth parity, the plan pays the allowed amount minus the payer's `copay_cents`, floored at zero — that is, `plan_paid_cents` is the allowed amount less the copay, but never below zero. If the payer does not offer parity, the plan pays only the non-parity share: take half of the allowed amount (the allowed amount multiplied by 0.50, rounded half-up to a whole cent), subtract the payer's `copay_cents`, and floor the result at zero. In both parity branches the final `plan_paid_cents` is never negative.

### 3.7. Prescribing: DEA Schedules, Authority, and the Recency Window

A `Physician` authors a prescription on one of their visits by supplying the `drug_name`, the `dea_schedule`, and the `days_supply`, and — for controlled substances — the `expected_visit_prescription_version` OCC token. The `dea_schedule` is one of `NONE` (a non-controlled drug), or the controlled schedules `II`, `III`, `IV`, and `V`. The `days_supply` must be strictly greater than zero. A prescription may be authored only while the parent visit is in `COMPLIANCE_CLEARED`, `APPROVED_INSURANCE`, or `APPROVED_SELF_PAY` status — a cleared or approved, non-terminal visit; authoring against a visit in any other status is rejected with `ERR_INVALID_STATE`. A newly authored prescription has `status` `ACTIVE` and records its visit through `visit_id`.

Controlled substances (`dea_schedule` other than `NONE`) carry three further gates. The first is authority: the prescribing physician must carry a `dea_number` that is not null, *and* the visit's governing license — the `StateLicense` named by the clearing `ComplianceCheck`'s `matched_license_id` — must have `controlled_substance_authority` set to true. A controlled-substance authoring that lacks either the federal DEA number or the state controlled-substance authority is rejected with `ERR_NO_CONTROLLED_AUTHORITY`.

The second gate is the DEA in-person-exam recency-and-modality rule. The platform looks for the physician's most recent qualifying prior in-state visit with this same patient: among `COMPLETED` visits sharing the same `patient_id`, the same `physician_id`, and the same `determined_state_code`, it takes the one with the greatest completion time, where a visit's completion time is its `updated_at` at the instant it reached `COMPLETED`; ties are broken by greatest completion time and then earliest `created_at`. The recency condition is satisfied when such a prior visit exists and the whole-day difference between the logical clock's `current_utc` and that visit's completion time is at most 180 days — the boundary day, a difference of exactly 180 days, still satisfies the window. The modality and recency requirements then combine by schedule: for a schedule `II` drug, both the recency condition must hold *and* the current visit's `modality` must be `VIDEO` (the strictest case); for a schedule `III`, `IV`, or `V` drug, it suffices that *either* the recency condition holds or the current modality is `VIDEO`. A non-controlled prescription (`NONE`) is exempt from this rule. A controlled-substance authoring that fails the applicable recency-and-modality requirement is rejected with `ERR_DEA_EXAM_REQUIRED`.

The third gate is the optimistic-concurrency check of §2.7, evaluated against the visit's `prescription_version`. When a new controlled-substance prescription is authored for the *same* `drug_name` as a prior `ACTIVE` prescription on the same visit, and the supplied `expected_visit_prescription_version` matches the visit's current `prescription_version`, the new prescription becomes the `ACTIVE` one, the prior prescription of that drug transitions from `ACTIVE` to `SUPERSEDED`, and the visit's `prescription_version` is incremented by one. A controlled-substance authoring for a *different* drug creates a new `ACTIVE` prescription without superseding anything. If the supplied `expected_visit_prescription_version` does not match the visit's current `prescription_version`, the authoring is rejected with `ERR_STALE_PRESCRIPTION_VERSION`.

When several of these checks could apply to a single authoring call, the platform evaluates them in a fixed order. After the universal authentication, authorization, and existence checks, it confirms the request body is well-formed (required fields present, enums in range, `days_supply` greater than zero) — failing here yields `ERR_INVALID_REQUEST`. It then confirms the visit is in an allowable state, then the DEA recency-and-modality rule, then the controlled-substance authority rule, and finally the stale-version OCC check. Thus a malformed body surfaces before any state objection, a state objection before the DEA recency objection, and the recency objection before the authority objection, with the stale-version rejection evaluated last.

### 3.8. Completing a Visit and the Follow-Up Cycle

A `Physician` completes an approved visit — whether it is `APPROVED_INSURANCE` or `APPROVED_SELF_PAY`, both forks transition to `COMPLETED` — and completion generates a follow-up. As a cascade of completion, the platform creates a `FollowUp` recording the just-completed visit through its `source_visit_id`, with `status` `OPEN`, a null `linked_visit_id`, and a computed `due_at`. The `due_at` is the visit's completion time (its `updated_at` at the instant it reached `COMPLETED`) plus a follow-up interval of thirty days.

A follow-up is closed in one of two ways. A `Physician` fulfills an open follow-up by supplying the `linked_visit_id` of the new visit booked to satisfy it; this sets the follow-up's `linked_visit_id` and moves its `status` from `OPEN` to `FULFILLED`. Alternatively, a `ComplianceOfficer` may lapse an open follow-up, but only once it is genuinely overdue: lapsing is permitted only when the logical clock's `current_utc` is at or after the follow-up's `due_at`, moving the `status` to `LAPSED`. An attempt to lapse a follow-up before its due instant has been reached is rejected with `ERR_NOT_DUE`.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource (registering a physician, patient, or payer; requesting a visit; issuing a state license; authoring a prescription) return a `201 Created` status code. Operations that modify or transition an existing resource, and all read operations, return a `200 OK` status code.

The table below is a routing summary only. The request bodies, response side effects, and validation rules for each endpoint are specified in the §3 narratives above and must be read there.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/physicians` | Register a physician | Anonymous |
| GET | `/physicians/{id}` | Fetch a physician | Anonymous, Physician, LicensingBoard, ComplianceOfficer |
| GET | `/physicians` | List physicians | Anonymous, LicensingBoard, ComplianceOfficer |
| POST | `/physicians/{id}/deactivate` | Deactivate a physician registry record | LicensingBoard |
| POST | `/physicians/{id}/state-licenses` | Issue a state license to a physician | LicensingBoard |
| GET | `/physicians/{id}/state-licenses` | List a physician's state licenses | Anonymous, Physician, LicensingBoard, ComplianceOfficer |
| GET | `/state-licenses/{id}` | Fetch a state license | Anonymous, Physician, LicensingBoard, ComplianceOfficer |
| POST | `/state-licenses/{id}/suspend` | Suspend a state license (cascades) | LicensingBoard |
| POST | `/state-licenses/{id}/reinstate` | Reinstate a suspended license | LicensingBoard |
| POST | `/state-licenses/{id}/revoke` | Revoke a state license | LicensingBoard |
| POST | `/patients` | Register a patient | Anonymous |
| GET | `/patients/{id}` | Fetch a patient | Anonymous, Patient, Physician, ComplianceOfficer |
| GET | `/patients` | List patients | Anonymous, ComplianceOfficer |
| POST | `/payers` | Register an insurance payer | Anonymous, ComplianceOfficer |
| GET | `/payers/{id}` | Fetch a payer | Anonymous, Patient, Physician, ComplianceOfficer |
| POST | `/visits` | Request a telemedicine visit | Patient |
| GET | `/visits/{id}` | Fetch a visit | Patient, Physician, LicensingBoard, ComplianceOfficer |
| GET | `/visits` | List visits filtered by physician and/or patient | Physician, Patient, LicensingBoard, ComplianceOfficer |
| POST | `/visits/{id}/run-compliance` | Run licensure + modality compliance | Physician |
| POST | `/visits/{id}/override-compliance` | Override a recorded blocked check | ComplianceOfficer |
| POST | `/visits/{id}/approve` | Approve a cleared visit and route payment | Physician |
| POST | `/visits/{id}/complete` | Mark an approved visit completed | Physician |
| POST | `/visits/{id}/cancel` | Cancel a not-yet-approved visit | Patient |
| GET | `/visits/{id}/compliance-checks` | List compliance checks for a visit | Physician, LicensingBoard, ComplianceOfficer |
| GET | `/state-licenses/{id}/compliance-checks` | List compliance checks governed by a license | LicensingBoard, ComplianceOfficer |
| POST | `/visits/{id}/prescriptions` | Author a prescription on a visit | Physician |
| GET | `/visits/{id}/prescriptions` | List prescriptions authored on a visit | Physician, Patient, LicensingBoard, ComplianceOfficer |
| GET | `/prescriptions/{id}` | Fetch a prescription | Physician, Patient, LicensingBoard, ComplianceOfficer |
| GET | `/visits/{id}/claims` | List claims for a visit | Physician, ComplianceOfficer |
| GET | `/claims/{id}` | Fetch a claim | Physician, ComplianceOfficer |
| GET | `/claims` | List claims filtered by payer | ComplianceOfficer |
| POST | `/claims/{id}/adjudicate` | Adjudicate a submitted claim | ComplianceOfficer |
| GET | `/visits/{id}/follow-ups` | List follow-ups generated by a visit | Physician, Patient, ComplianceOfficer |
| GET | `/follow-ups/{id}` | Fetch a follow-up | Physician, Patient, ComplianceOfficer |
| GET | `/follow-ups` | List follow-ups filtered by linked visit | Physician, Patient, ComplianceOfficer |
| POST | `/follow-ups/{id}/fulfill` | Link a new visit to an open follow-up | Physician |
| POST | `/follow-ups/{id}/lapse` | Mark an overdue open follow-up lapsed | ComplianceOfficer |
| POST | `/_clock/set` | Set the platform current UTC instant | Anonymous, ComplianceOfficer |
| GET | `/_clock` | Read the platform current UTC instant | Anonymous, Physician, Patient, LicensingBoard, ComplianceOfficer |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 422 |
| `ERR_DUPLICATE_RESOURCE` | 409 |
| `ERR_COMPACT_INELIGIBLE` | 422 |
| `ERR_LICENSE_PERIOD_OVERLAP` | 409 |
| `ERR_VISIT_SLOT_CONFLICT` | 409 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_DEA_EXAM_REQUIRED` | 422 |
| `ERR_NO_CONTROLLED_AUTHORITY` | 422 |
| `ERR_MODALITY_NOT_PERMITTED` | 422 |
| `ERR_NO_LICENSE_IN_STATE` | 422 |
| `ERR_STALE_PRESCRIPTION_VERSION` | 412 |
| `ERR_PAGINATION_INVALID` | 422 |
| `ERR_NOT_DUE` | 409 |
