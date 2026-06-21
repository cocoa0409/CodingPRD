# Business License & Permit API — Product Requirements Document

## 1. Introduction

Municipal licensing offices sit at the intersection of three competing pressures: applicants who want a predictable, fast path from "I want to open a restaurant" to a license in hand; field inspectors and licensing officers who must enforce zoning, safety, and fee rules without colluding to wave a business through; and the city treasury, which expects every charge, reversal, penalty, and transfer fee to net out correctly. This API is the system of record that mediates all three. It governs the full lifecycle of a local business permit — from registering a business and choosing the activity rulebook that applies to it, through zoning clearance, inspection, approval, and issuance, into the recurring renewal cycle, and finally into the terminal events of revocation, surrender, or ownership transfer.

The design treats the activity an applicant intends to perform as the root of all downstream rules. An **ActivityCategory** is a reusable rulebook that fixes the fee schedule, the number of inspections required, whether a zoning check is mandatory, the validity term, and the set of zones in which the activity is permitted outright. Every application points at exactly one such rulebook, and the same rulebook later governs the license it produces. Two recurring tensions shape the business logic throughout this document: the difference between a *provisional* number computed early (a fee estimate at submission, a risk score at approval) and the *final* audited number computed later (the binding issuance fee, the recomputed risk score at delinquency), and the strict **segregation of duties** that prevents the officer who inspected a premises from also being the officer who issues its license.

A note on time: because licensing is inherently temporal — terms expire, grace periods elapse, renewal windows open and close — the system keeps a logical clock that test operators can advance explicitly. All temporal computations (delinquency, renewal eligibility, revocation thresholds) read this server clock rather than wall-clock time.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, envelope conventions, and cross-cutting principles that apply across every endpoint. Domain-specific workflows are detailed in Section 3.

### 2.1. User and Role-Based Access Control

Every request must carry two mandatory HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. The system recognizes exactly three roles, spelled precisely as follows: `Applicant`, `LicensingOfficer`, and `InspectionOfficer`. A request that omits either header, or that names a role outside this set, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is recognized but not permitted to perform the requested operation is rejected with `ERR_UNAUTHORIZED` (HTTP 403). These two checks run first, before any resource lookup or business rule.

The meaning of `X-User-ID` depends on the role. When `X-User-Role` is `Applicant`, `X-User-ID` is the `id` of the acting `Business`; ownership checks on any resource that references a `Business` compare the resource's business foreign-key field to `X-User-ID`. When `X-User-Role` is `LicensingOfficer`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server records it where a scaffold transition writes it — for example, as `reviewed_by_user_id` on an `Application` when that officer approves or rejects — but it never compares that identifier to any entity's `id`. Likewise, when `X-User-Role` is `InspectionOfficer`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server records it as `inspector_user_id` on an `Inspection` the officer performs, but does not compare it to any entity's `id`. This recorded inspector identity is precisely what the issuance-time segregation-of-duties check later consults.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps how many items are returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter is the number of items to skip and defaults to 0. A `limit` or `offset` outside its allowed range is rejected with `ERR_PAGINATION_INVALID` (HTTP 400).

Unless a specific endpoint states otherwise, all list results are sorted by `created_at` in ascending order. Every list response includes `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope.

### 2.4. Validation Ordering and the Error Precedence Ladder

Because most write operations are guarded by several checks at once, the order in which they fire is part of the contract — a later, more specific rejection must never mask an earlier, more general one. The system evaluates guards in a fixed precedence. Authentication comes first: missing or unknown-role headers yield `ERR_UNAUTHENTICATED`. Authorization comes second: a recognized but unpermitted role yields `ERR_UNAUTHORIZED`. Resource existence comes third: any resource named in the path or body that does not exist yields `ERR_NOT_FOUND`, with path identifiers validated left-to-right (see §2.8). Request well-formedness comes fourth: a missing required field, a wrongly typed value, or an enum value outside its allowed set yields `ERR_INVALID_REQUEST` (HTTP 400). State legality comes fifth: if the target resource is not in a state from which the requested transition is defined, the request is rejected with `ERR_INVALID_STATE` (HTTP 409). Only after these five tiers pass does the system evaluate the domain-specific business rules described throughout §2 and §3 (segregation of duties, inspection prerequisites, standing, transferability, zoning, renewal windows, revocation thresholds, outstanding fees, optimistic concurrency, and uniqueness).

A distinct, deeper validation tier exists for inputs that are well-typed but semantically out of bounds. A `declared_employee_count` below zero, a `verified_employee_count` or `failed_item_count` below zero, an `activity_base_risk` outside the inclusive range 0 through 40, a `required_inspection_count` outside the inclusive range 0 through 5, a `risk_tier` that is not one of the recognized tiers, or a `term_months` that is not one of the recognized terms — each of these passes a bare type check yet is rejected with `ERR_VALIDATION` (HTTP 422).

### 2.5. Common Resource Properties

Most resources in this system are mutable, audited entities and carry a standard system-managed property set. `Business`, `Application`, `Inspection`, `License`, `Endorsement`, `OwnershipTransfer`, and `FeeAssessment` each expose:

- `id` — a server-minted UUID with no type prefix, used for addressability only and never accepted as a business-decision input.
- `created_at` — an ISO 8601 UTC timestamp with three fractional digits, fixed at creation.
- `updated_at` — an ISO 8601 UTC timestamp with three fractional digits, refreshed on every mutation.
- `version` — an integer that starts at its initial value of 1 and increments by one on every mutation of the resource. It is the anchor for optimistic concurrency (see §2.7).

The `ActivityCategory` entity is the lone exception. As an immutable configuration rulebook, it carries only `id` and `created_at`; it has no `updated_at` and no `version`. Tooling and clients must not expect either field on an activity category.

Whenever a transition's side effects say a resource's version increments, that increment is accompanied by a refresh of `updated_at`; the two move together. This includes server-initiated mutations of derived fields — for example, when a license's delinquency cascade demotes a business and rewrites its `standing` and `compliance_risk_score`, the business's `version` and `updated_at` advance even though no client touched the business directly.

### 2.6. Monetary Precision and Risk-Score Clamping

All money fields — `estimated_fee`, `final_fee`, `transfer_fee`, and the `amount` on a fee assessment — are represented as plain numbers rounded to exactly two decimal places using round-half-up. Every fee formula in §3 sums its components first and rounds the final sum once (sum-then-round); it never rounds intermediate terms. The `compliance_risk_score`, by contrast, is an integer: after its weighted contributions are summed it is clamped to the inclusive range 0 through 100 — any negative result floors to 0 and any result above 100 caps at 100.

### 2.7. Optimistic Concurrency on Transfer Completion

Completing an approved ownership transfer reassigns a license to a new holder, and that license's `version` is the concurrency anchor that guards against acting on a stale view. The completion request must carry `expected_license_version`, a non-optional field holding the `version` of the target license that the client last observed. If `expected_license_version` does not equal the license's current `version`, the completion is rejected with `ERR_STALE_VERSION` (HTTP 412). This rejection fires whenever another writer has advanced the license's version since the client read it — for instance, the license was renewed, or a competing transfer against the same license already completed — so the current writer's reassignment would clobber newer state. No other endpoint accepts or requires a version field; completion is the sole optimistic-concurrency-guarded operation.

### 2.8. Left-to-Right Path Resolution and Reverse-Reachability Reads

Several read endpoints reach a collection through a parent identifier — for example, the applications filed by a business, the inspections gating an application, the endorsements or transfers or fee assessments attached to a license. For any such path, the system validates each identifier in left-to-right order and rejects with `ERR_NOT_FOUND` at the first identifier that does not resolve to an existing resource, before attempting to read anything further down the path. A request for the inspections of a non-existent application fails on the application, not on the inspection collection.

### 2.9. The Fee Ledger and Its Conservation Invariant

Money in this system is never overwritten in place; it accrues as an append-only ledger of `FeeAssessment` records. Each assessment is charged against either a license (via its `license_id`) or an application (via its `application_id`), with the unused side left null, and carries a `kind` drawn from `APPLICATION_FEE`, `ISSUANCE_FEE`, `RENEWAL_FEE`, `DELINQUENCY_PENALTY`, `TRANSFER_FEE`, and `REVERSAL`. The `amount` is signed: a positive amount is a charge, a negative amount is a reversal or credit. Each assessment also tracks whether it has been paid via the boolean `settled`, which begins false and is set true when the assessment is settled.

The ledger obeys a compensation invariant: when a charge must be undone — an application is rejected or withdrawn after its application fee was assessed — the system does not delete the original charge but appends a `REVERSAL` assessment whose amount is the negative of the original, so that the net application-stage ledger returns to zero. This append-and-compensate discipline is what lets the surrender path safely insist that a license carry no outstanding unsettled assessments before it may be relinquished.

## 3. Business Logic & Workflows

### 3.1. The Activity Rulebook and Business Registration

Everything begins with two foundational records. A `LicensingOfficer` defines an `ActivityCategory`, supplying its human-readable activity `code` (for example, a food-service or general-retail code), its `risk_tier` (one of `LOW`, `MEDIUM`, or `HIGH`), its `activity_base_risk` (the base contribution this activity makes to a business's compliance risk, an integer from 0 through 40 inclusive), its `required_inspection_count` (how many distinct passed inspections a license in this category demands, from 0 through 5 inclusive), its `requires_zoning_check` flag, its `term_months` (the validity term granted at issuance and added at each renewal, one of 12, 24, or 36), and its `allowed_zones` (a non-empty list of zone codes in which the activity is permitted outright, without a variance). The `code` must be unique across all activity categories and is immutable once created; an attempt to create a second category with an existing code is rejected with `ERR_DUPLICATE_ACTIVITY_CODE` (HTTP 409). Because an activity category is a configuration rulebook, it is the only entity without `updated_at` or `version`.

A business is registered with its `legal_name`, the `owner_name` of its current principal owner of record, and the `zone_code` of its premises address. On registration its derived regulatory `standing` is initialized to `GOOD`, its `prior_revocation_flag` to false, and its `compliance_risk_score` to 0. Standing is one of `GOOD`, `DELINQUENT`, or `REVOKED`, and it gates two things downstream: a business must be in `GOOD` standing to submit a new application, and a business must be in `GOOD` standing to be the receiving party of an ownership transfer. The `prior_revocation_flag` is a sticky marker — it becomes true the first time any license of the business reaches `REVOKED` and is never cleared thereafter, and it permanently adds weight to the business's risk score.

### 3.2. Filing and Submitting an Application

An `Applicant` opens an `Application` in `DRAFT` by naming the applicant `business_id`, the chosen `activity_category_id`, the `declared_employee_count` the applicant claims, and the `requested_zone_code` declared for the premises on this filing. A fresh application starts with `status` `DRAFT` and `zoning_status` `PENDING`; its `estimated_fee` is initialized to 0 (no fee is computed until submission), and both `reviewed_by_user_id` and `license_id` start null. The application's lifecycle `status` is one of `DRAFT`, `SUBMITTED`, `ZONING_CLEARED`, `VARIANCE_REQUIRED`, `APPROVED`, `REJECTED`, `ISSUED`, or `WITHDRAWN`, with `ISSUED`, `REJECTED`, and `WITHDRAWN` being terminal.

Submitting a draft moves it `DRAFT → SUBMITTED`. Two preconditions guard the submission: the application must currently be in `DRAFT`, and the referenced business must be in `GOOD` standing — a business whose standing is not `GOOD` causes the submission to fail with `ERR_BUSINESS_NOT_IN_GOOD_STANDING` (HTTP 409). On a successful submission the system computes the provisional application fee into `estimated_fee` and opens an `APPLICATION_FEE` assessment against the application for that amount, unsettled. This provisional estimate is the *first* of the two-variant fee story: it is the base fee for the activity's risk tier, plus a per-employee surcharge applied to the **declared** head count, plus a zoning variance surcharge only if the application is already flagged as requiring a variance (which at submission time it is not, so the variance term is zero here). Concretely, the estimate is the base fee for the risk tier — 100.00 for `LOW`, 250.00 for `MEDIUM`, 600.00 for `HIGH` — plus 5.00 multiplied by the declared employee count, plus a 150.00 variance surcharge when the application's `zoning_status` is `VARIANCE_REQUIRED` and nothing otherwise, with the three components added together and the total rounded once to two decimal places using round-half-up.

An applicant may abandon an application by withdrawing it, which is permitted while it is in any of `DRAFT`, `SUBMITTED`, `ZONING_CLEARED`, or `VARIANCE_REQUIRED` and which drives it to the terminal `WITHDRAWN` state. If at the moment of withdrawal an unsettled `APPLICATION_FEE` assessment exists, the system appends a `REVERSAL` assessment for the negative of the estimated fee so the applicant owes nothing for an application they walked away from.

### 3.3. Zoning Clearance and the Variance Branch

Once submitted, an application must pass a zoning check run by a `LicensingOfficer`, and this is where the lifecycle forks. The check is only defined from the `SUBMITTED` state. When the `requested_zone_code` is one of the category's `allowed_zones`, the application clears: it advances `SUBMITTED → ZONING_CLEARED` and its `zoning_status` is set to `CLEARED`. When the `requested_zone_code` is *not* among the allowed zones, the outcome depends on whether the category tolerates a variance. If the category's `requires_zoning_check` is true, the application takes the variance branch, advancing `SUBMITTED → VARIANCE_REQUIRED` with its `zoning_status` set to `VARIANCE_REQUIRED`; on this branch the system recomputes `estimated_fee` to include the 150.00 zoning variance surcharge and correspondingly raises the open `APPLICATION_FEE` assessment's `amount` to match the new estimate. If the requested zone is outside the allowed set and the category does not permit a variance path, the check is denied outright with `ERR_ZONING_DENIED` (HTTP 409).

Both the cleared branch and the variance branch are legitimate paths toward approval; they differ only in the surcharge already baked into the assessment. A reviewing officer treats them symmetrically from here on, except that an application carrying the variance surcharge keeps that 150.00 in every later fee that re-reads the variance flag.

### 3.4. Inspections and the Issuance Prerequisite

Inspections are scheduled and recorded by an `InspectionOfficer` and are the gate that stands between approval and a real license. Scheduling an inspection records the `application_id` it gates and the `inspector_user_id` of the officer performing it, and the inspection opens with `result` `SCHEDULED`; the officer may also supply `verified_employee_count` and `failed_item_count` at scheduling, though these are typically filled in when the outcome is recorded; either count omitted at scheduling defaults to 0. Recording an outcome sets `result` to either `PASSED` or `FAILED` and writes the on-site `verified_employee_count` (the head count actually observed, which later overrides the declared figure for the binding fee) and the `failed_item_count` (the number of failed line items, which later feeds the audited risk score). An outcome may only be recorded against an inspection still in `SCHEDULED`; recording against one already resolved is rejected with `ERR_INSPECTION_ALREADY_RECORDED` (HTTP 409). The inspection `result` is one of `SCHEDULED`, `PASSED`, or `FAILED`.

Approval is the officer's gate before issuance, and it is reachable from either zoning branch: `ZONING_CLEARED → APPROVED` or `VARIANCE_REQUIRED → APPROVED`. Both branches share the same prerequisite: the count of this application's inspections whose `result` is `PASSED` must be at least the category's `required_inspection_count`. If too few passed inspections exist, approval is rejected with `ERR_INSPECTION_PREREQUISITE_NOT_MET` (HTTP 409). On approval from either branch the officer's `X-User-ID` is recorded into `reviewed_by_user_id`, and the system computes a *provisional* compliance risk score for the business. This provisional variant scores the business before any inspection findings are aggregated: it starts from the activity's `activity_base_risk`, treats the open-violation count as zero (so the violation contribution is nothing at this stage), adds a delinquency weight only if the business is currently `DELINQUENT` and a prior-revocation weight only if its `prior_revocation_flag` is set, then clamps to 0 through 100. The two branches are otherwise identical, save that the variance branch's surcharge is already sitting on the assessment and needs no recomputation at approval.

A `LicensingOfficer` may instead reject an application that is in any of `SUBMITTED`, `ZONING_CLEARED`, or `VARIANCE_REQUIRED`, driving it to terminal `REJECTED`. Rejection records the officer's `X-User-ID` into `reviewed_by_user_id` and appends a `REVERSAL` assessment for the negative of the estimated fee, reversing the application-fee charge so that the net application ledger returns to zero.

### 3.5. Issuance: the Final Fee and Segregation of Duties

Issuance turns an `APPROVED` application into a live `License`, advancing the application `APPROVED → ISSUED`. This is the convergence point of the whole front half of the workflow — both the cleared and the variance approval paths arrive here. Two preconditions guard it. First, the application must be `APPROVED`. Second, and central to the integrity of the process, the issuing officer's `X-User-ID` must differ from every `inspector_user_id` recorded on any inspection of this application: an officer who inspected the premises may not also issue its license. A violation of this segregation of duties is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403).

Issuance creates the license in `ACTIVE` status with `business_id`, `application_id`, and `activity_category_id` copied from the source application, sets `issued_on` to the current clock instant and `expires_on` to that instant advanced by the category's `term_months`, initializes `renewal_count` to 0, sets the application's `license_id` to the new license, and marks the application `ISSUED`. It then computes the binding `final_fee` — the *second* variant of the fee story, and the one that actually charges the holder. The final fee substitutes the **verified** employee count from the latest passed inspection for the declared count and adds an inspection fee per passed inspection. Precisely: it is the base fee for the activity's risk tier (100.00 for `LOW`, 250.00 for `MEDIUM`, 600.00 for `HIGH`), plus 5.00 multiplied by the verified employee count, plus the 150.00 zoning variance surcharge when the application's `zoning_status` is `VARIANCE_REQUIRED` and nothing otherwise, plus 75.00 multiplied by the number of this application's inspections whose `result` is `PASSED`; the four components are summed and the total is rounded once to two decimal places using round-half-up. Because it reads verified rather than declared counts and adds inspection fees, the final fee differs from the earlier estimate whenever the counts diverge or any inspection passed. The system opens an `ISSUANCE_FEE` assessment against the new license for the final fee, unsettled.

### 3.6. The Renewal Cycle and Delinquency

A license's lifecycle `status` is one of `ACTIVE`, `DELINQUENT`, `REVOKED`, or `SURRENDERED`, with `REVOKED` and `SURRENDERED` terminal. The temporal machinery that drives this cycle reads the server's logical clock, which a `LicensingOfficer` advances by supplying a `to_iso8601` instant through the test-driving clock capability; every delinquency, renewal, and revocation computation thereafter uses that instant as "now."

A license may be renewed by its `Applicant` from either `ACTIVE` (an in-cycle renewal, `ACTIVE → ACTIVE`) or `DELINQUENT` (a recovery renewal, `DELINQUENT → ACTIVE`). Renewal is only permitted once the renewal window has opened — that is, when the current clock instant is at or after the license's `expires_on` minus the renewal window of 60 days. A renewal attempted before that window opens is rejected with `ERR_RENEWAL_WINDOW_CLOSED` (HTTP 409). Renewal from the delinquent state additionally requires that no unsettled `DELINQUENCY_PENALTY` assessment remain unless that penalty is being paid as part of this renewal. Every renewal advances `expires_on` by the category's `term_months` anchored to the current `expires_on`, increments `renewal_count` by one, and settles the license's outstanding `RENEWAL_FEE` and `DELINQUENCY_PENALTY` assessments. An in-cycle renewal from `ACTIVE` creates and immediately settles a `RENEWAL_FEE` and carries no penalty. A recovery renewal from `DELINQUENT` additionally restores standing: if the holding business has no other license still in `DELINQUENT` or `REVOKED`, its `standing` returns to `GOOD` and its `compliance_risk_score` is recomputed.

Delinquency is assessed by a `LicensingOfficer` against the clock, taking an `ACTIVE` license whose `expires_on` lies strictly before the current clock instant and moving it `ACTIVE → DELINQUENT`; an `ACTIVE` license whose `expires_on` is not strictly before the current clock instant is rejected with `ERR_INVALID_STATE` (HTTP 409). The assessment first measures `days_overdue` as the number of whole UTC days from `expires_on` to now, computed by taking the elapsed time and discarding any fractional day (floor). The penalty is tiered and single-tier — the license pays the rate of the one tier its overdue count falls into, and the tiers do not stack. If `days_overdue` is at most the 30-day grace period, the penalty rate is zero. If it is greater than 30 but at most 60 days, the rate is 10 percent. If it is greater than 60 but at most 90 days, the rate is 25 percent. If it is greater than 90 days, the rate is 50 percent. The penalty is that rate multiplied by the base renewal fee for the license's risk tier — 200.00 for `LOW`, 480.00 for `MEDIUM`, 900.00 for `HIGH` — rounded to two decimal places using round-half-up. The delinquency assessment always opens a `RENEWAL_FEE` assessment for the renewal fee, and additionally opens a `DELINQUENCY_PENALTY` assessment for the penalty whenever the penalty is greater than zero. It then sets the holding `Business`'s `standing` to `DELINQUENT` and recomputes its `compliance_risk_score` under the audited variant.

The *audited* compliance risk score differs from the provisional one computed at approval in both its inputs and its result. Where the provisional variant treats the open-violation count as zero, the audited variant sets the open-violation count to the sum of `failed_item_count` across this business's inspections. The score is the activity's `activity_base_risk` — read from the category of the business's most-recently-created application (or 0 if the business has no application or that application's category is unresolved) — plus the violation contribution — 5 per open violation, but that violation contribution is capped at 30 so additional violations beyond the cap add nothing — plus 20 if the business's `standing` is `DELINQUENT`, plus 10 if its `prior_revocation_flag` is set, with the final sum clamped to the inclusive range 0 through 100. For the same business, the audited score is at least as high as the provisional one whenever failed items exist or the business is delinquent.

### 3.7. Revocation and Surrender: the Terminal Cascades

Revocation is the punitive terminus, performed by a `LicensingOfficer` on a `DELINQUENT` license, advancing it `DELINQUENT → REVOKED`. It is gated on time: revocation is only permitted once `days_overdue` exceeds the revocation threshold of 90 days; an attempt before that threshold is rejected with `ERR_REVOCATION_THRESHOLD_NOT_REACHED` (HTTP 409). Revocation triggers a three-level cascade. First, every endorsement of the license currently in `ACTIVE` or `SUSPENDED` is driven to `VOIDED`. Second, every ownership transfer of the license currently in `REQUESTED` or `APPROVED` is cancelled, and that cancellation itself sets the transfer's `transfer_fee` to zero. Third, the holding business is set to `REVOKED` standing, its `prior_revocation_flag` is set to true, and its `compliance_risk_score` is recomputed under the audited variant. Each of these mutated resources advances its own `version` and `updated_at`.

Surrender is the voluntary terminus, performed by an `Applicant` on an `ACTIVE` license, advancing it `ACTIVE → SURRENDERED`. It is gated fiscally: a license may be surrendered only when it has no outstanding unsettled `FeeAssessment`; if any unsettled assessment remains, the surrender is rejected with `ERR_OUTSTANDING_FEES` (HTTP 409). On surrender, every endorsement of the license currently in `ACTIVE` is driven to `VOIDED`.

### 3.8. Endorsements and Conditions

An endorsement attaches a regulatory condition or special permission to a license. A `LicensingOfficer` creates one against a `license_id` with a `kind` — one of `LATE_HOURS`, `OUTDOOR_SEATING`, `HAZMAT_HANDLING`, or `SIDEWALK_USE` — and a free-text `condition_text` describing the imposed condition. An endorsement's lifecycle `status` is one of `ACTIVE`, `SUSPENDED`, or `VOIDED`, beginning `ACTIVE`, with `VOIDED` terminal. A `LicensingOfficer` may suspend an `ACTIVE` endorsement (`ACTIVE → SUSPENDED`), which requires that the parent license be in `ACTIVE` or `DELINQUENT`; may reinstate a `SUSPENDED` endorsement (`SUSPENDED → ACTIVE`), which requires that the parent license be `ACTIVE`; and may void an endorsement that is in `ACTIVE` or `SUSPENDED` (`ACTIVE → VOIDED`), either directly or as the cascade consequence of a license revocation or surrender described in §3.7. Each of these transitions advances the endorsement's `version`.

### 3.9. Ownership Transfer

An ownership transfer moves a license from one business to another. A transfer is requested — by an `Applicant` or a `LicensingOfficer` — by naming the `license_id` being transferred, the `from_business_id` of the current holder of record, and the `to_business_id` of the prospective new holder. It opens in `REQUESTED` status; its lifecycle `status` is one of `REQUESTED`, `APPROVED`, `REJECTED`, `COMPLETED`, or `CANCELLED`, with `REJECTED`, `COMPLETED`, and `CANCELLED` terminal. A transfer may only target a license that is `ACTIVE`; at request, approval, and completion, a license that is `DELINQUENT`, `REVOKED`, or `SURRENDERED` causes rejection with `ERR_LICENSE_NOT_TRANSFERABLE` (HTTP 409).

A `LicensingOfficer` approves a requested transfer (`REQUESTED → APPROVED`), which additionally requires that the license be `ACTIVE` and that the business named by `to_business_id` be in `GOOD` standing — a receiving business not in good standing causes `ERR_BUSINESS_NOT_IN_GOOD_STANDING` (HTTP 409). An officer may instead reject a requested transfer (`REQUESTED → REJECTED`). A transfer in `REQUESTED` or `APPROVED` may be cancelled — by an `Applicant` or `LicensingOfficer`, or as the cascade from a license revocation — driving it to `CANCELLED` and setting its `transfer_fee` to zero.

Completing an approved transfer (`APPROVED → COMPLETED`) is the binding act, performed by a `LicensingOfficer`, and it is the system's one optimistic-concurrency-guarded operation. The completion must be in `APPROVED` status, the license must still be `ACTIVE`, and the request must carry `expected_license_version` equal to the license's current `version`; a mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412) as detailed in §2.7. On completion the license's `business_id` is reassigned to `to_business_id` (only the holding business moves; the owner-of-record name is not copied), the system computes the `transfer_fee` and opens a `TRANSFER_FEE` assessment against the license for it, and both the license's `version` and the transfer's `version` advance. The transfer fee is a flat 300.00, plus a 200.00 risk surcharge only when the license's activity `risk_tier` is `HIGH` and nothing otherwise, with the two components summed and rounded to two decimal places using round-half-up.

### 3.10. Settling Fees and the Logical Clock

Any open assessment may be settled — marking its `settled` flag true — by either an `Applicant` or a `LicensingOfficer` recording payment against it. Settlement is what eventually clears the outstanding-fee gate on surrender and what a recovery renewal performs implicitly for the renewal fee and any delinquency penalty.

The logical clock is operated only by a `LicensingOfficer`, who sets the server's current UTC instant by supplying `to_iso8601`; from that point forward every temporal computation in the system — delinquency overdue days, renewal-window eligibility, revocation thresholds, and the `issued_on`/`expires_on` math at issuance — reads that instant as the present moment. The clock-setting capability returns 200 OK with an empty `data` object (`{}`) rather than any resource.

## 4. Endpoint Definitions

Operations that create a new, standalone resource return `201 Created`; operations that modify an existing resource, including state transitions and settlement, return `200 OK`. The clock-setting capability returns `200 OK`. Request bodies, response bodies, and side effects are not restated here — reconstruct them from the workflow narratives in §3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/activity-categories` | Create an activity-category rulebook entry | LicensingOfficer |
| GET | `/activity-categories/{id}` | Fetch an activity category | LicensingOfficer, InspectionOfficer, Applicant |
| GET | `/activity-categories` | List activity categories | LicensingOfficer, InspectionOfficer, Applicant |
| POST | `/businesses` | Register a business | Applicant, LicensingOfficer |
| GET | `/businesses/{id}` | Fetch a business with derived standing and risk score | Applicant, LicensingOfficer, InspectionOfficer |
| GET | `/businesses/{id}/applications` | List applications for a business | Applicant, LicensingOfficer, InspectionOfficer |
| GET | `/businesses/{id}/licenses` | List licenses held by a business | Applicant, LicensingOfficer, InspectionOfficer |
| POST | `/applications` | Create a draft application | Applicant |
| GET | `/applications/{id}` | Fetch an application | Applicant, LicensingOfficer, InspectionOfficer |
| GET | `/applications` | List applications, optionally filtered | Applicant, LicensingOfficer, InspectionOfficer |
| POST | `/applications/{id}/submit` | Submit a draft application; compute provisional fee | Applicant |
| POST | `/applications/{id}/zoning-check` | Run zoning check; clear or flag variance | LicensingOfficer |
| POST | `/applications/{id}/approve` | Approve an application meeting zoning and inspection prerequisites | LicensingOfficer |
| POST | `/applications/{id}/reject` | Reject an application; reverse the application fee | LicensingOfficer |
| POST | `/applications/{id}/withdraw` | Withdraw an application; reverse unsettled application fee | Applicant |
| POST | `/applications/{id}/issue` | Issue a license from an approved application | LicensingOfficer |
| GET | `/applications/{id}/inspections` | List inspections for an application | LicensingOfficer, InspectionOfficer, Applicant |
| GET | `/applications/{id}/fee-assessments` | List fee assessments tied to an application | LicensingOfficer, Applicant |
| POST | `/inspections` | Schedule an inspection for an application | InspectionOfficer |
| GET | `/inspections/{id}` | Fetch an inspection | LicensingOfficer, InspectionOfficer, Applicant |
| POST | `/inspections/{id}/record` | Record inspection outcome with verified counts and failed items | InspectionOfficer |
| GET | `/licenses/{id}` | Fetch a license | Applicant, LicensingOfficer, InspectionOfficer |
| GET | `/licenses` | List licenses, optionally filtered | Applicant, LicensingOfficer, InspectionOfficer |
| POST | `/licenses/{id}/assess-delinquency` | Evaluate a license against the clock; demote and assess penalty if overdue | LicensingOfficer |
| POST | `/licenses/{id}/renew` | Renew a license; advance expiry and settle outstanding fees | Applicant |
| POST | `/licenses/{id}/revoke` | Revoke a delinquent license past the revocation threshold | LicensingOfficer |
| POST | `/licenses/{id}/surrender` | Surrender an active license with no outstanding fees | Applicant |
| GET | `/licenses/{id}/endorsements` | List endorsements on a license | Applicant, LicensingOfficer, InspectionOfficer |
| GET | `/licenses/{id}/transfers` | List ownership transfers for a license | Applicant, LicensingOfficer |
| GET | `/licenses/{id}/fee-assessments` | List fee assessments tied to a license | LicensingOfficer, Applicant |
| POST | `/endorsements` | Attach a condition/endorsement to a license | LicensingOfficer |
| GET | `/endorsements/{id}` | Fetch an endorsement | Applicant, LicensingOfficer, InspectionOfficer |
| POST | `/endorsements/{id}/suspend` | Suspend an active endorsement | LicensingOfficer |
| POST | `/endorsements/{id}/reinstate` | Reinstate a suspended endorsement | LicensingOfficer |
| POST | `/endorsements/{id}/void` | Void an endorsement | LicensingOfficer |
| POST | `/transfers` | Request an ownership transfer of a license | Applicant, LicensingOfficer |
| GET | `/transfers/{id}` | Fetch an ownership transfer | Applicant, LicensingOfficer |
| GET | `/transfers` | List ownership transfers, optionally filtered | Applicant, LicensingOfficer |
| POST | `/transfers/{id}/approve` | Approve a requested transfer | LicensingOfficer |
| POST | `/transfers/{id}/reject` | Reject a requested transfer | LicensingOfficer |
| POST | `/transfers/{id}/complete` | Complete an approved transfer (OCC on license version) | LicensingOfficer |
| POST | `/transfers/{id}/cancel` | Cancel a requested/approved transfer | Applicant, LicensingOfficer |
| GET | `/fee-assessments/{id}` | Fetch a fee assessment | LicensingOfficer, Applicant |
| POST | `/fee-assessments/{id}/settle` | Mark a fee assessment settled | LicensingOfficer, Applicant |
| POST | `/_clock/set_current_utc` | Set the server's current UTC clock (test-driving) | LicensingOfficer |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_INSPECTION_PREREQUISITE_NOT_MET` | 409 |
| `ERR_BUSINESS_NOT_IN_GOOD_STANDING` | 409 |
| `ERR_LICENSE_NOT_TRANSFERABLE` | 409 |
| `ERR_ZONING_DENIED` | 409 |
| `ERR_RENEWAL_WINDOW_CLOSED` | 409 |
| `ERR_REVOCATION_THRESHOLD_NOT_REACHED` | 409 |
| `ERR_OUTSTANDING_FEES` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_DUPLICATE_ACTIVITY_CODE` | 409 |
| `ERR_VALIDATION` | 422 |
| `ERR_INSPECTION_ALREADY_RECORDED` | 409 |
| `ERR_PAGINATION_INVALID` | 400 |
</content>
</invoke>
