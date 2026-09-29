# Organ Procurement Donor Management API — Product Requirements Document

## 1. Introduction

An Organ Procurement Organization (OPO) lives or dies by its clock. A partner hospital's obligation to call in a death referral is measured in minutes; a serologic contraindication discovered after clearance must invalidate a conversion that is already in motion; a heart tolerates roughly four hours of cold ischemia between cross-clamp and implantation, and every minute lost to logistics is a minute stolen from a recipient. Today these facts live in spreadsheets, paging systems and telephone logs that do not talk to each other, and the OPO discovers a contradiction only when a surgical team is already airborne.

This document specifies the Organ Procurement Donor Management API, mounted under the `/opo` prefix. The service carries a donor from the moment a hospital's clinical trigger fires — through eligibility screening, behavioral risk assessment, serologic testing, first-person-registry or next-of-kin authorization, donor physiologic management, national match-run allocation with acceptance clocks, recovery surgery and transport — to the final disposition of every organ, whether transplanted, discarded, or referred for research or tissue processing. Above that pipeline sits a performance-reporting layer that reproduces the timeliness, conversion and organs-per-donor ratios on which the OPO's federal recertification depends.

Two design commitments shape the whole specification. First, the OPO is a **regulated custodian**, not merely a scheduler: consent is legally revocable, a duty performed by one person may not be ratified by that same person, and any fact that invalidates a donor must propagate downward through organs, match runs, offers and booked operating rooms without a human remembering to do it. Second, the system is **deterministic under test**: every timestamp is drawn from a logical clock that an administrator drives explicitly, so the same sequence of calls always produces the same lag minutes, the same expiry sweeps and the same cold-ischemic projections.

## 2. Global Specifications & System-Wide Principles

This section defines the rules that hold across every endpoint. Where §3 narrates a workflow, this section supplies the invariants that workflow must not violate.

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. If either header is absent, or if the value of `X-User-Role` is not one of the nine declared role names, the request is rejected with `ERR_UNAUTHENTICATED` (401 Unauthorized). If the headers are well formed but the acting role is not among the roles authorized for the requested operation in the §4 table, the request is rejected with `ERR_FORBIDDEN_ROLE` (403 Forbidden).

The nine roles are, in full: `OpoAdmin`, `HospitalReferralClerk`, `ReferralCoordinator`, `SerologyLab`, `MedicalDirector`, `AuthorizationSpecialist`, `DonorCoordinator`, `AllocationSpecialist` and `RecoveryLogistics`. Their remits: `OpoAdmin` registers hospitals, recovery teams and transport assets, reads the performance report, and sets the logical clock. `HospitalReferralClerk` places death referral calls on behalf of one hospital. `ReferralCoordinator` takes the referral, opens the eligibility screening and submits the behavioral risk assessment. `SerologyLab` files serologic marker results. `MedicalDirector` requests additional history, rules on eligibility, evaluates organs and records final dispositions. `AuthorizationSpecialist` runs the registry search, walks the next-of-kin hierarchy, files documents and finalizes the packet. `DonorCoordinator` converts a referral into a donor case, charts physiologic observations and registers organs. `AllocationSpecialist` generates match runs, advances acceptance clocks and records transplant-centre responses. `RecoveryLogistics` books operating-room windows, records cross-clamp and dispatches organ transport.

Identity semantics differ by role and must be implemented precisely. When `X-User-Role` is `HospitalReferralClerk`, `X-User-ID` is the `id` of the acting `HospitalPartner`; ownership checks on any resource that references a `HospitalPartner` compare the resource's hospital foreign-key field to `X-User-ID`. Concretely, a clerk creating a death referral must supply a `hospital_partner_id` equal to its own `X-User-ID`, and a clerk reading a hospital partner may read only the hospital whose `id` equals its own `X-User-ID`; either violation is rejected with `ERR_HOSPITAL_SCOPE_VIOLATION` (403 Forbidden). For all eight other roles — `OpoAdmin`, `ReferralCoordinator`, `SerologyLab`, `MedicalDirector`, `AuthorizationSpecialist`, `DonorCoordinator`, `AllocationSpecialist` and `RecoveryLogistics` — `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server records it where a workflow demands an audit counterparty (as `risk_assessed_by_user_id` and `decided_by_user_id` on a screening, as `recorded_by_user_id` on a next-of-kin contact, as `consent_recorded_by_user_id` and `finalized_by_user_id` on an authorization, as `recorded_by_user_id` on a physiologic observation, and as `responded_by_user_id` on an organ offer) but never compares it to any entity's `id`.

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

List endpoints accept two query parameters. `limit` caps the number of items returned; it defaults to 10, its minimum accepted value is 1, and its maximum accepted value is 100. `offset` skips a number of leading items and defaults to 0; its minimum accepted value is 0. A `limit` that is not an integer or falls outside 1 through 100 inclusive, or an `offset` that is not an integer or is negative, is rejected with `ERR_INVALID_PAGINATION` (400 Bad Request).

Unless a specific endpoint states otherwise, list results are sorted by `created_at` in ascending order. The one documented exception is the offer listing for a match run, which is ordered by `sequence_position` ascending so that the national sequence reads top to bottom.

Every list response carries `limit`, `offset`, `total_count` and `has_more` inside the `meta` object of the envelope, where `total_count` is the number of matching rows before the limit and offset are applied and `has_more` indicates whether further rows remain beyond the current page.

### 2.4. Resource Identity, Timestamps and the Logical Clock

Each persisted resource carries a server-minted `id` formatted as a UUID with no type prefix, and a `created_at` timestamp rendered as an ISO 8601 UTC instant with exactly three fractional digits. Most resources additionally carry `updated_at`, an ISO 8601 UTC instant refreshed on every mutation of the resource, and `version`, an integer that starts at 1 and increments by one on every mutation. Refreshing a derived counter — a hospital's `referral_count`, a case's `viability_index`, a run's `pending_offer_count` — counts as a mutation of the owning resource and therefore advances both `updated_at` and `version` on that resource.

Three resources are append-only records rather than managed aggregates, and they carry **only** `id` and `created_at`: a `SerologyResult`, a `NextOfKinContact`, and a `PhysiologicObservation`. For these three, both `updated_at` and `version` are absent from the response body entirely — not null, absent. The remaining eleven resource kinds — hospital partners, death referrals, eligibility screenings, authorizations, donor cases, organs, match runs, organ offers, recovery teams, recovery operations and transport assets — carry the full quartet of `id`, `created_at`, `updated_at` and `version`.

All domain time is read from a **logical clock**, never from wall-clock time. Before any administrator sets it, the clock reads exactly `2026-08-01T00:00:00Z`, and it never falls back to wall-clock time under any circumstance. An `OpoAdmin` may move it forward or backward by supplying a `to_iso8601` instant; the response reports the resulting `current_utc`. Every system-stamped instant reads from this clock: `referred_at` on a referral, `contacted_at` on a next-of-kin contact, `generated_at` on a match run, `offered_at` and the derived `expires_at` and `responded_at` on an offer, and `cross_clamp_at` on a recovery operation and on the organs it recovers.

### 2.5. Path Resolution, Foreign Keys and Terminal-State Refusal

When a request path contains more than one resource identifier, the identifiers are resolved strictly left to right, and the first one that does not resolve determines the error. The relevant not-found codes are `ERR_HOSPITAL_NOT_FOUND`, `ERR_REFERRAL_NOT_FOUND`, `ERR_SCREENING_NOT_FOUND`, `ERR_AUTHORIZATION_NOT_FOUND`, `ERR_DONOR_CASE_NOT_FOUND`, `ERR_ORGAN_NOT_FOUND`, `ERR_MATCH_RUN_NOT_FOUND`, `ERR_OFFER_NOT_FOUND` and `ERR_OPERATION_NOT_FOUND`, each returned with 404 Not Found. A response to an offer that names a non-existent match run therefore yields `ERR_MATCH_RUN_NOT_FOUND` before the offer identifier is examined at all.

Foreign keys supplied in a request body are resolved after path identifiers and before any body-shape validation. A `hospital_partner_id` that names no hospital yields `ERR_HOSPITAL_NOT_FOUND`; a `referral_id` that names no referral yields `ERR_REFERRAL_NOT_FOUND`; an `authorization_id` that names no authorization yields `ERR_AUTHORIZATION_NOT_FOUND`; a `recovery_team_id` that names no team yields `ERR_TEAM_NOT_FOUND`; a `transport_asset_id` that names no asset yields `ERR_ASSET_NOT_FOUND`. All five are 404 Not Found.

Body shape is then checked: every required field must be present, every value must match its declared type, every enumerated value must be a declared member of its enumeration, and every numeric value must fall inside its declared range. Any failure yields `ERR_INVALID_REQUEST` (400 Bad Request). Uniqueness is enforced on `hospital_code`, `team_code`, `asset_code`, `donor_code`, and on the pair of a donor case together with an `organ_type`; a collision on any of these yields `ERR_DUPLICATE_KEY` (409 Conflict).

Finally, a general refusal protects finished lifecycles. When the resource named in the path already sits in one of its own declared terminal states, every further transition trigger against it is rejected with `ERR_ALREADY_TERMINAL` (409 Conflict). The scope of this rule is pinned deliberately: it reads **only** the path resource's own state machine, and it is **not** evaluated for either of a donor case's two status dimensions. A case whose `physiologic_status` is `LOST` or whose `allocation_status` is `CLOSED` is gated instead by the posture rule of §2.8, which returns `ERR_CASE_FROZEN`; that is the declared vehicle for the whole donor-case family.

### 2.6. Minute Arithmetic, Ratios and Rounding

Elapsed-time quantities are always whole minutes obtained by taking the difference of two instants in seconds, dividing by sixty, and discarding any fractional remainder downward. This applies to a referral's `referral_lag_minutes` and `audit_lag_minutes`, to an operation's `or_minutes`, and to an organ's `transit_minutes` and the elapsed-since-cross-clamp component of its cold-ischemic projection. A gap of 119 seconds is therefore one minute, not two.

Ratios and scores are computed with decimal arithmetic and rounded half up to exactly two decimal places. This governs a screening's `risk_score` (rounded once per contribution and once more after the cap), a hospital's `timely_referral_rate`, and the report's `conversion_rate` and `organs_per_donor`. Point-based and count-based quantities — a case's `viability_index`, an observation's `viability_index_snapshot`, a run's `pending_offer_count` and `slots_free`, a team's `booked_or_minutes` — are integers throughout and need no rounding.

Every threshold comparison in this specification is inclusive at the stated floor unless the text says otherwise. Where a rule genuinely requires strict comparison — the ordering of an operating-room end against its start, the ordering of a transport arrival against its departure, the acceptance clock's not-yet-elapsed test — the text says "strictly".

### 2.7. Stale-View Protection on Screening and Organ Writes

Two write operations are guarded by optimistic concurrency control, because both are operations whose *repetition* is legitimate and whose *blind* repetition is dangerous.

A request to `POST /opo/eligibility-screenings/{id}/risk-assessment` must carry `expected_screening_version` as a non-optional field, holding the `version` of the `EligibilityScreening` that the client last observed. Resubmitting an assessment is perfectly valid — a coordinator reaches a better informant and supersedes the earlier scoring — so no state precondition forbids it; the only guard is that the assessment was composed against the screening the client actually read. If `expected_screening_version` does not equal the screening's current `version`, the request is rejected with `ERR_STALE_VERSION` (HTTP 412 Precondition Failed).

A request to `POST /opo/organs/{id}/match-runs` must carry `expected_organ_version` as a non-optional field, holding the `version` of the `Organ` that the client last observed. Generating a later run legitimately supersedes the organ's earlier open run — the organ is re-listed after fresh donor data arrives — so again no state precondition blocks it; the guard is only that the requester's view of the organ is current. If `expected_organ_version` does not equal the organ's current `version`, the request is rejected with `ERR_STALE_VERSION` (HTTP 412 Precondition Failed). Because a successful match-run generation itself increments the organ's `version` by one, a client that generates two runs back to back must re-read the organ in between.

No other endpoint accepts a version field, and no other endpoint performs a version check.

### 2.8. Donor Case Posture: the Two-Dimensional Gate

A `DonorCase` carries two **independent** status dimensions. `physiologic_status` describes the donor's body and takes the values `STABILIZING`, `OPTIMIZED`, `DECOMPENSATING` and `LOST`. `allocation_status` describes the placement of organs and takes the values `NOT_STARTED`, `MATCH_RUN_OPEN`, `OFFERS_IN_FLIGHT`, `ALLOCATED`, `RECOVERED` and `CLOSED`. Neither dimension constrains the other directly; a donor may be `DECOMPENSATING` while its liver sits in `OFFERS_IN_FLIGHT`.

What couples them is a derived third value, `case_posture`, recomputed after any mutation of either dimension and after any rescission of the case's authorization. Its derivation has strict, pinned precedence: if `allocation_status` is `CLOSED`, **or** `physiologic_status` is `LOST`, **or** the authorization named by the case's `authorization_id` has reached `RESCINDED`, then `case_posture` is `FROZEN`. Otherwise, if `physiologic_status` is `DECOMPENSATING`, `case_posture` is `RESTRICTED`. Otherwise it is `OPEN`. `FROZEN` always wins over `RESTRICTED`, which always wins over `OPEN`.

The three postures gate differently. `OPEN` imposes no gate. `RESTRICTED` refuses organ evaluation and match-run generation for any organ whose `organ_type` is one of the three thoracic types — `HEART`, `LUNG_LEFT` or `LUNG_RIGHT` — with `ERR_POSTURE_RESTRICTED` (409 Conflict); abdominal organs proceed untouched. `FROZEN` refuses every child mutation of the case with `ERR_CASE_FROZEN` (409 Conflict): charting an observation, registering an organ, evaluating an organ, generating a match run, responding to an offer, booking a recovery operation, recording cross-clamp, and dispatching transport. Recording an organ's final disposition is deliberately **exempt** from the frozen gate, because research and tissue book-keeping for organs stranded by a closure must remain recordable after the case freezes.

### 2.9. Segregation of Duties

Two decisions in the pipeline require two different human beings, and the system enforces that mechanically rather than by policy. The `MedicalDirector` who issues a screening decision must not be the user whose `X-User-ID` is recorded in `risk_assessed_by_user_id` on that screening. The `AuthorizationSpecialist` who finalizes an authorization packet must not be the user whose `X-User-ID` is recorded in `consent_recorded_by_user_id` on that packet. Either violation is rejected with `ERR_SEGREGATION_OF_DUTIES` (403 Forbidden).

The second check is vacuous on the registry branch of authorization: a packet confirmed from the first-person registry never records a consent-taker, so `consent_recorded_by_user_id` is null and any specialist may finalize it.

### 2.10. Rejection Precedence

When several rules could reject one request, the outcome is fully determined by the following evaluation order. Earlier rules mask later ones, so the ordering is part of the contract and not an implementation detail.

1. **Header presence and role validity** — `ERR_UNAUTHENTICATED`, on every endpoint.
2. **Role authorization for the endpoint** — `ERR_FORBIDDEN_ROLE`, on every endpoint.
3. **Hospital scoping for a clerk** — `ERR_HOSPITAL_SCOPE_VIOLATION`, on `POST /opo/death-referrals` and `GET /opo/hospital-partners/{id}`.
4. **Path identifier existence, left to right** — the nine 404 codes of §2.5, on every path-templated endpoint.
5. **Body foreign-key existence** — the five 404 codes of §2.5, on `POST /opo/death-referrals`, `POST /opo/donor-cases`, `POST /opo/donor-cases/{id}/recovery-operations` and `POST /opo/organs/{id}/transport`.
6. **Body shape, types, enum membership and numeric ranges** — `ERR_INVALID_REQUEST`, on every POST endpoint.
7. **Pagination bounds** — `ERR_INVALID_PAGINATION`, on `GET /opo/death-referrals`, `GET /opo/donor-cases`, `GET /opo/organs` and `GET /opo/recovery-operations`.
8. **Unique-key availability** — `ERR_DUPLICATE_KEY`, on `POST /opo/hospital-partners`, `POST /opo/recovery-teams`, `POST /opo/transport-assets`, `POST /opo/donor-cases` and `POST /opo/donor-cases/{id}/organs`.
9. **Referral screenability** — `ERR_REFERRAL_NOT_SCREENABLE`, on `POST /opo/death-referrals/{id}/screenings`.
10. **Screening action status** — `ERR_SCREENING_NOT_PENDING`, on `POST /opo/eligibility-screenings/{id}/risk-assessment`, `POST /opo/eligibility-screenings/{id}/request-info` and `POST /opo/eligibility-screenings/{id}/decision`.
11. **Risk assessment present before a ruling** — `ERR_RISK_ASSESSMENT_MISSING`, on `POST /opo/eligibility-screenings/{id}/decision`.
12. **Authorization openability** — `ERR_AUTHORIZATION_NOT_OPENABLE`, on `POST /opo/death-referrals/{id}/authorizations`.
13. **Authorization contactability** — `ERR_AUTHORIZATION_NOT_CONTACTABLE`, on `POST /opo/authorizations/{id}/nok-contacts`.
14. **Authorization finalizability and upload admissibility** — `ERR_AUTHORIZATION_NOT_FINALIZABLE`, on `POST /opo/authorizations/{id}/finalize` and `POST /opo/authorizations/{id}/documents`.
15. **Screening cleared for conversion** — `ERR_SCREENING_NOT_CLEARED`, on `POST /opo/donor-cases`.
16. **Authorization granted for conversion** — `ERR_AUTHORIZATION_NOT_GRANTED`, on `POST /opo/donor-cases`.
17. **Organ status for the requested action** — `ERR_ORGAN_NOT_EVALUABLE` on `POST /opo/organs/{id}/evaluation`, `ERR_ORGAN_NOT_ALLOCATABLE` on `POST /opo/organs/{id}/match-runs`, `ERR_ORGAN_NOT_RECOVERED` on `POST /opo/organs/{id}/transport`.
18. **Offer status for the requested response** — `ERR_OFFER_NOT_PENDING`, on `POST /opo/match-runs/{id}/offers/{offerId}/respond`.
19. **Acceptance clock not elapsed** — `ERR_ACCEPTANCE_CLOCK_ELAPSED`, on `POST /opo/match-runs/{id}/offers/{offerId}/respond`.
20. **Operation, run and disposition status** — `ERR_OPERATION_NOT_SCHEDULED` on `POST /opo/recovery-operations/{id}/cross-clamp` and `POST /opo/recovery-operations/{id}/cancel`, `ERR_MATCH_RUN_NOT_OPEN` on `POST /opo/match-runs/{id}/advance`, `ERR_DISPOSITION_NOT_ALLOWED` on `POST /opo/organs/{id}/disposition`.
21. **Terminal-state refusal** — `ERR_ALREADY_TERMINAL`, on every POST action endpoint, with the pinned scope described in §2.5.
22. **Stale-view rejection** — `ERR_STALE_VERSION`, on `POST /opo/organs/{id}/match-runs` and `POST /opo/eligibility-screenings/{id}/risk-assessment`.
23. **Segregation of duties** — `ERR_SEGREGATION_OF_DUTIES`, on `POST /opo/eligibility-screenings/{id}/decision` and `POST /opo/authorizations/{id}/finalize`.
24. **Absolute contraindication** — `ERR_ABSOLUTE_CONTRAINDICATION`, on `POST /opo/eligibility-screenings/{id}/decision` and `POST /opo/donor-cases`.
25. **Frozen case posture** — `ERR_CASE_FROZEN`, on the eight child mutations enumerated in §2.8.
26. **Active viability hold** — `ERR_VIABILITY_HOLD_ACTIVE`, on `POST /opo/organs/{id}/evaluation`. This check is deliberately ordered **before** the posture gate that follows it, because the hold is the more specific fact: a held organ always sits on a restricted case, so the coarser posture error would otherwise mask it.
27. **Restricted case posture** — `ERR_POSTURE_RESTRICTED`, on `POST /opo/organs/{id}/evaluation` and `POST /opo/organs/{id}/match-runs`.
28. **Increased-risk acknowledgement** — `ERR_INCREASED_RISK_ACK_REQUIRED`, on `POST /opo/match-runs/{id}/offers/{offerId}/respond`.
29. **Documentation completeness at finalize** — `ERR_AUTHORIZATION_DOCUMENTATION_INCOMPLETE`, on `POST /opo/authorizations/{id}/finalize`.
30. **Next-of-kin hierarchy admissibility** — `ERR_NOK_HIERARCHY_VIOLATION`, on `POST /opo/authorizations/{id}/nok-contacts`.
31. **Referral not before its trigger** — `ERR_REFERRAL_BEFORE_TRIGGER`, on `POST /opo/death-referrals`.
32. **Observation not in the future** — `ERR_OBSERVATION_IN_FUTURE`, on `POST /opo/donor-cases/{id}/observations`.
33. **Time-window ordering** — `ERR_INVALID_TIME_WINDOW`, on `POST /opo/donor-cases/{id}/recovery-operations` and `POST /opo/organs/{id}/transport`.
34. **Cold-ischemic ceiling** — `ERR_COLD_ISCHEMIC_LIMIT_EXCEEDED`, on `POST /opo/organs/{id}/transport`.
35. **Team specialty coverage** — `ERR_TEAM_SPECIALTY_MISMATCH`, on `POST /opo/donor-cases/{id}/recovery-operations`.
36. **Authorization and referral agreement** — `ERR_AUTHORIZATION_REFERRAL_MISMATCH`, on `POST /opo/donor-cases`.
37. **Offer belongs to the path's run** — `ERR_OFFER_RUN_MISMATCH`, on `POST /opo/match-runs/{id}/offers/{offerId}/respond`.
38. **At least one accepted organ** — `ERR_NO_ACCEPTED_ORGANS`, on `POST /opo/donor-cases/{id}/recovery-operations`.
39. **Candidate list well-formedness** — `ERR_EMPTY_MATCH_RUN` and `ERR_INVALID_SEQUENCE`, on `POST /opo/organs/{id}/match-runs`.
40. **Information-request budget** — `ERR_INFO_REQUEST_LIMIT_REACHED`, on `POST /opo/eligibility-screenings/{id}/request-info`.
41. **Buffered team availability** — `ERR_TEAM_WINDOW_CONFLICT`, on `POST /opo/donor-cases/{id}/recovery-operations`.
42. **Transport asset capacity** — `ERR_ASSET_CAPACITY_EXCEEDED`, on `POST /opo/organs/{id}/transport`.
43. **Disposition preconditions** — `ERR_DISPOSITION_NOT_ALLOWED`, on `POST /opo/organs/{id}/disposition`.

### 2.11. Cascades and Conserved Quantities

Some facts in this domain invalidate work that has already been done, and the system propagates them without waiting for a client to ask. Two cascades are declared, and both run to completion inside the single request that triggers them.

The **rescission cascade** begins when a higher-ranked relative objects to an authorization that has already reached `AUTHORIZED`, and runs five hops deep: the authorization is rescinded; the referral and the donor case are closed; the case's organs are marked non-transplantable; their open match runs are closed and their live offers bypassed; and their scheduled recovery operations are cancelled, which releases the booked operating-room minutes back to the surgical team. The **decompensation cascade** begins when a new physiologic observation drops a donor's viability, and runs four hops: the physiologic dimension moves to `DECOMPENSATING`; the posture becomes `RESTRICTED`; thoracic organs are pulled back for re-evaluation under a viability hold; and the match runs and offers behind those organs are closed and bypassed. §3 narrates the exact field-level consequences of each hop.

Two quantities are conserved and must reconcile after every step. First, for each match run, `pending_offer_count` plus `slots_free` always equals `primary_offer_slots`. Second, for each recovery team, `booked_or_minutes` is always exactly the sum of `or_minutes` over that team's operations whose status is `SCHEDULED` or `COMPLETED`, and `scheduled_operation_count` is always exactly the number whose status is `SCHEDULED`. Any forward action that adds to these ledgers has a compensating action that removes from them.

## 3. Business Logic & Workflows

### 3.1. Hospital Partners and the Death Referral Intake

Before any referral can be recorded, an `OpoAdmin` registers each referring hospital with its legal `name` and a short operating `hospital_code` of between 2 and 12 characters that must be unique across all hospitals. Two policy fields accompany the registration. The `referral_trigger_policy` states which clinical event obliges the hospital to call the OPO and is one of `VENTILATED_NEURO_INJURY`, `ALL_VENTILATED_DEATHS` or `ALL_DEATHS`, defaulting to `VENTILATED_NEURO_INJURY`. The `timely_referral_window_minutes` states how many minutes may elapse between that trigger and the call; it must be an integer from 1 through 1440 and defaults to 60 — one hour, the industry norm. A freshly registered hospital starts with `referral_count`, `timely_referral_count`, `untimely_referral_count` and `converted_donor_count` all at zero, `timely_referral_rate` at null, and `partner_posture` at `GOOD_STANDING`.

Recording a referral is the intake event. Either a `HospitalReferralClerk` acting for its own hospital or an OPO-side `ReferralCoordinator` submits the `hospital_partner_id`, the hospital's own `patient_mrn` for the decedent, the decedent's `age_years` as a whole number from 0 through 100, a `ventilated` boolean stating whether the patient was on mechanical ventilation at the trigger event, the `gcs_score` as a Glasgow Coma Scale total from 3 through 15, a `cause_of_death_category` drawn from `ANOXIA`, `CVA_STROKE`, `HEAD_TRAUMA`, `CNS_TUMOR` or `OTHER`, and the `trigger_event_at` instant at which the hospital's configured trigger was first met. An optional `death_pronounced_at` may also be supplied; it defaults to null. The server stamps `referred_at` from the logical clock and the new referral enters status `RECEIVED`.

Two temporal orderings are checked before anything is computed. The stamped `referred_at` must not precede `trigger_event_at`, and `death_pronounced_at`, when supplied, must not precede `trigger_event_at` either. A violation of either ordering is rejected with `ERR_REFERRAL_BEFORE_TRIGGER`.

**Timeliness is scored on two bases at intake.** For each basis, the lag is the number of whole minutes from the basis instant to `referred_at`, taking the difference in seconds, dividing by sixty and discarding the fraction downward. Under the clinical-trigger basis the basis instant is `trigger_event_at`, and the resulting value is stored as `referral_lag_minutes`. Under the death-note basis the basis instant is `death_pronounced_at`, and the resulting value is stored as `audit_lag_minutes`; when `death_pronounced_at` is null, `audit_lag_minutes` is null. Because death is pronounced at or after the trigger fires, the death-note lag is never larger than the clinical-trigger lag, so the same referral can look timely on one basis and untimely on the other. Only the clinical-trigger basis sets the persisted `timeliness_flag`: it is `TIMELY` when `referral_lag_minutes` is less than or equal to the hospital's `timely_referral_window_minutes`, with equality counting as timely, and `UNTIMELY` otherwise. The window is pinned from the hospital row as it stands at intake; a later edit to the hospital's window never restates a referral already stored.

**The hospital's lifetime standing is then updated in place.** Its `referral_count` increases by one. Its `timely_referral_count` increases by one when the new referral's `timeliness_flag` is `TIMELY`, and its `untimely_referral_count` increases by one when the flag is `UNTIMELY`. The `timely_referral_rate` becomes null if `referral_count` is zero, and otherwise becomes one hundred multiplied by `timely_referral_count`, divided by `referral_count`, rounded half up to two decimal places. The `partner_posture` is then re-derived in a fixed order: if `referral_count` is below four the sample is too small to judge and the posture is `GOOD_STANDING` regardless of rate; otherwise, a rate of at least 75.00 gives `GOOD_STANDING`, a rate of at least 60.00 gives `WATCH`, and anything lower gives `PROBATION`. This lifetime denominator counts **every** referral the hospital has ever placed — ventilated or not, ruled out or not — and its numerator uses each referral's stored flag.

Referrals may be listed with optional filters on `hospital_partner_id`, `status` and `timeliness_flag`, which doubles as the reverse lookup from a hospital to its referrals.

### 3.2. Eligibility Screening: Behavioral Risk, Serology and the Director's Ruling

A `ReferralCoordinator` opens screening on a referral that is still in `RECEIVED` and for which no screening yet exists; the referral advances `RECEIVED → SCREENING` and a new `EligibilityScreening` is created in status `PENDING` with `info_request_count` at zero, carrying the `referral_id` of the referral it screens. If the referral is in any other status, or a screening already exists for it, the attempt is rejected with `ERR_REFERRAL_NOT_SCREENABLE`. The screening may be reached either by its own identifier or by reverse lookup from the referral, which returns an array of length zero or one.

**The behavioral risk assessment.** The coordinator submits the decedent's behavioral history as `risk_factors`, an array of factor members; `informant_reliability`, naming the quality of the history source as `PRIMARY_NEXT_OF_KIN`, `SECONDARY_CONTACT` or `MEDICAL_RECORD_ONLY`; the `expected_screening_version` described in §2.7; and optionally `unresolved_factors`, an array of factors the informant could neither confirm nor exclude, which defaults to the empty array and must be disjoint from `risk_factors`. The assessment is accepted while the screening is in `PENDING` or in `INFO_REQUESTED`; from any other status it is rejected with `ERR_SCREENING_NOT_PENDING`. Only the factors in the current request body count: the prior assessment on the screening is **fully replaced**, never merged.

The seven scored factors and their weights are `IV_DRUG_USE_12MO` at 6.50, `UNKNOWN_MEDICAL_SOCIAL_HISTORY` at 5.00, `INCARCERATION_72H_12MO` at 4.25, `NEW_SEX_PARTNER_HIGH_RISK_12MO` at 3.75, `HEMODIALYSIS_12MO` at 2.50, `BLOOD_TRANSFUSION_12MO` at 2.00 and `TATTOO_UNREGULATED_12MO` at 1.50. That listing order is the **canonical order** in which factors are scored, and it is used regardless of the order the client sent them in and regardless of any identifier ordering. The informant's reliability supplies a multiplier: 1.00 for `PRIMARY_NEXT_OF_KIN`, 1.15 for `SECONDARY_CONTACT` and 1.30 for `MEDICAL_RECORD_ONLY`.

Scoring proceeds as a list of contributions. The reported factors are de-duplicated and walked in canonical order, and each one contributes its weight multiplied by the reliability multiplier, that product rounded half up to two decimal places. Under the **records-only** variant — which applies exactly when `informant_reliability` is `MEDICAL_RECORD_ONLY` — the unresolved factors are then de-duplicated, walked in the same canonical order, and each one contributes its weight multiplied by one half and then by the reliability multiplier, that product likewise rounded half up to two decimal places; `risk_variant_applied` is set to `RECORDS_ONLY`. Under the **interview-based** variant — which applies when `informant_reliability` is `PRIMARY_NEXT_OF_KIN` or `SECONDARY_CONTACT` — the unresolved factors are ignored entirely and `risk_variant_applied` is set to `INTERVIEW_BASED`. The same reported factor list therefore scores strictly higher under the records-only variant whenever any unresolved factor is present.

The order of rounding and summing is pinned and material: **each contribution is rounded to two decimal places first, and only then are the rounded contributions added together.** Summing the unrounded products and rounding once at the end is wrong and differs by whole cents. The sum is then capped at 25.00 — the smaller of the sum and 25.00 is taken — and the capped value is rounded half up to two decimal places once more to give `risk_score`. Finally `risk_tier` becomes `INCREASED_RISK` when `risk_score` is at least 12.00 and `STANDARD` otherwise. Submitting the assessment also records the submitting operator in `risk_assessed_by_user_id`, moves a screening that was in `INFO_REQUESTED` back to `PENDING`, leaves a screening that was already in `PENDING` in `PENDING`, and increments the screening's `version` by one.

**The information-request cycle.** A `MedicalDirector` may bounce a screening in `PENDING` back to the coordinator for more behavioral history, optionally attaching an `info_request_note`. The screening moves `PENDING → INFO_REQUESTED` and its `info_request_count` increases by one. This is permitted at most twice per screening: an attempt made while `info_request_count` already stands at two is rejected with `ERR_INFO_REQUEST_LIMIT_REACHED`. A fresh risk assessment closes the cycle by returning the screening `INFO_REQUESTED → PENDING`.

**Serology.** The `SerologyLab` files laboratory results against a screening, each identifying its `screening_id`, the `marker` assayed — one of `HIV_AB`, `HIV_NAT`, `HBV_SAG`, `HCV_AB`, `HCV_NAT`, `CMV_IGG`, `EBV_IGG` or `SYPHILIS_RPR` — the `result` as `NEGATIVE`, `POSITIVE` or `INDETERMINATE`, the `resulted_at` instant at which the laboratory released it, and an optional `nat_confirmed` boolean stating whether a nucleic-acid test confirmed a positive, defaulting to false. The server derives `absolute_contraindication_marker` on the result: it is true when the `marker` is one of the four absolute markers `HIV_AB`, `HIV_NAT`, `HBV_SAG` or `HCV_NAT`, **and** the `result` is `POSITIVE`, **and** `nat_confirmed` is true. All three conditions must hold; a positive `HCV_AB`, or an unconfirmed positive `HIV_NAT`, is not an absolute contraindication.

When a filed result does carry an absolute marker and the screening is in `PENDING` or in `INFO_REQUESTED`, the system rules the donor out on the spot: the screening's `absolute_contraindication` flips to true, its `ruled_out_reason` becomes `SEROLOGY_CONTRAINDICATION`, its status moves to `RULED_OUT`, and the referral behind it moves `SCREENING → RULED_OUT`, which is terminal for the referral. Filing a result on a screening that has already reached `CLEARED` is a different case and is deliberately accepted: the record is stored, `absolute_contraindication` flips to true, the screening's status **stays** `CLEARED`, the referral is untouched, and no state transition occurs — the terminal-state refusal of §2.5 is not evaluated for a `CLEARED` screening. The contraindication then blocks conversion downstream instead. A screening in `RULED_OUT` is the one terminal state that does refuse further results, with `ERR_ALREADY_TERMINAL`, since no further clinical decision can turn on them.

**The director's ruling.** A `MedicalDirector` rules the screening by submitting a `decision` of either `CLEARED` or `RULED_OUT`, optionally with a `ruled_out_reason` drawn from `SEROLOGY_CONTRAINDICATION`, `MEDICAL_UNSUITABILITY`, `AGE_CRITERIA` or `DIRECTOR_DECISION`; when a rule-out carries no explicit reason, `DIRECTOR_DECISION` is stored. A ruling is accepted only from `PENDING`, otherwise `ERR_SCREENING_NOT_PENDING`. It requires that `risk_score` be non-null — that is, that an assessment has actually been submitted — and otherwise fails with `ERR_RISK_ASSESSMENT_MISSING`. It requires that the ruling operator differ from `risk_assessed_by_user_id`, per §2.9. And a clearance additionally requires `absolute_contraindication` to be false; attempting to clear a screening carrying an absolute contraindication fails with `ERR_ABSOLUTE_CONTRAINDICATION`. On success the ruling operator is recorded in `decided_by_user_id`. A clearance moves the screening `PENDING → CLEARED` and propagates the referral `SCREENING → SCREEN_CLEARED`; a rule-out moves the screening `PENDING → RULED_OUT` and propagates the referral `SCREENING → RULED_OUT`. Both screening states are terminal.

### 3.3. Authorization: the Registry Branch, the Next-of-Kin Hierarchy, Documentation and Rescission

An `AuthorizationSpecialist` opens the authorization packet on a referral in `SCREEN_CLEARED` for which no non-terminal authorization already exists — a packet in `DECLINED`, `UNABLE_TO_LOCATE` or `RESCINDED` is terminal and does not block a fresh attempt. Any other referral status, or a live packet already present, yields `ERR_AUTHORIZATION_NOT_OPENABLE`. Creation advances the referral `SCREEN_CLEARED → AUTH_PENDING`. The packet is created in `PENDING_REGISTRY` and immediately branches on the submitted `registry_hit` boolean, which reports whether the first-person donor registry returned a match for the decedent. The two branches carry deliberately **disjoint** consequences.

**Branch A — the registry hit.** When `registry_hit` is true, a `registry_document_ref` naming the registry match printout must accompany it. The packet moves `PENDING_REGISTRY → REGISTRY_CONFIRMED`, its `authorization_basis` becomes `FIRST_PERSON_REGISTRY`, its `required_document_types` becomes the single-member list containing `REGISTRY_SCREENSHOT`, that same `REGISTRY_SCREENSHOT` is added to `document_types_present` because the supplied reference is filed automatically, and `documentation_complete` becomes true. This branch arrives documentation-complete and needs no relatives contacted at all.

**Branch B — no registry hit.** When `registry_hit` is false, the packet moves `PENDING_REGISTRY → NOK_REQUIRED`, its `authorization_basis` becomes `LEGAL_NEXT_OF_KIN`, its `required_document_types` becomes the two-member list containing `SIGNED_CONSENT_FORM` and `WITNESS_ATTESTATION`, and `documentation_complete` becomes false. This branch must walk the statutory next-of-kin hierarchy and then upload two documents before it can be finalized.

**Walking the hierarchy.** Each contact attempt records the `authorization_id`, the `relationship` of the contacted person — `SPOUSE`, `ADULT_CHILD`, `PARENT`, `SIBLING`, `GRANDPARENT` or `LEGAL_GUARDIAN` — the `response` as `CONSENT`, `DECLINE`, `UNREACHABLE` or `OBJECTION`, and an optional free-text `contact_note`. The server derives the statutory `rank` from the relationship: a `SPOUSE` is rank 1, an `ADULT_CHILD` rank 2, a `PARENT` rank 3, a `SIBLING` rank 4, a `GRANDPARENT` rank 5 and a `LEGAL_GUARDIAN` rank 6, where 1 is the highest-priority class. It also stamps `contacted_at` from the logical clock and records the acting specialist in `recorded_by_user_id`. Contacts are accepted only while the packet is in `NOK_REQUIRED`, with one exception: an `OBJECTION` is also accepted while the packet is `AUTHORIZED`. Any other combination is rejected with `ERR_AUTHORIZATION_NOT_CONTACTABLE`.

Hierarchy admissibility governs which relative may speak for the decedent. A `CONSENT` or a `DECLINE` recorded at a given rank is admissible only when **every** rank numerically better than it — that is, every rank strictly lower in number — already has a contact on this packet whose response was `DECLINE` or `UNREACHABLE`. The condition is vacuously satisfied at rank 1, so a spouse's consent needs no predecessor; a consent recorded at rank 2 while no rank-1 contact exists is rejected with `ERR_NOK_HIERARCHY_VIOLATION`. Separately, a `CONSENT` is blocked outright when any contact at a better rank has already responded with `OBJECTION`. The packet's `highest_rank_attempted` — the numerically lowest rank for which a contact row exists, updated as the smaller of its current value and the new contact's rank — is a reporting field only and never relaxes this admissibility check.

The response then determines the packet's fate. A `CONSENT` moves the packet `NOK_REQUIRED → NOK_CONSENTED`, sets `consenting_rank` to the consenting relative's rank, and records the acting specialist in `consent_recorded_by_user_id`. A `DECLINE` **from rank 1** ends the packet: it moves `NOK_REQUIRED → DECLINED`, which is terminal, and propagates the referral `AUTH_PENDING → NOT_CONVERTED`, also terminal. A `DECLINE` from any rank above 1 does not end the packet; it merely records the attempt and updates `highest_rank_attempted`. An `UNREACHABLE` that leaves every one of the six relationship classes with a contact row on this packet, none of them a `CONSENT`, exhausts the hierarchy: the packet moves `NOK_REQUIRED → UNABLE_TO_LOCATE`, which is terminal, and the referral moves `AUTH_PENDING → NOT_CONVERTED`.

**Documentation and the deficiency cycle.** Filing a document supplies a `document_type` from `REGISTRY_SCREENSHOT`, `RECORDED_CONSENT_AUDIO`, `SIGNED_CONSENT_FORM` or `WITNESS_ATTESTATION`, and optionally a `witness_name` naming the person attesting the telephonic consent, which accompanies a `WITNESS_ATTESTATION` upload. The type is added to `document_types_present`, which is a set of distinct types — uploading the same type twice is idempotent — and `witness_name` is stored when supplied. Completeness is then recomputed from the basis: on the `FIRST_PERSON_REGISTRY` basis, `documentation_complete` is true exactly when `REGISTRY_SCREENSHOT` appears in `document_types_present`; on the `LEGAL_NEXT_OF_KIN` basis, it is true exactly when both `SIGNED_CONSENT_FORM` and `WITNESS_ATTESTATION` appear in `document_types_present` **and** `witness_name` is non-null. Uploads are accepted only while the packet is in `NOK_CONSENTED` or `DOCUMENT_DEFICIENT`; otherwise `ERR_AUTHORIZATION_NOT_FINALIZABLE`. An upload onto a packet in `DOCUMENT_DEFICIENT` returns it `DOCUMENT_DEFICIENT → NOK_CONSENTED`, closing the deficiency cycle; an upload onto a packet already in `NOK_CONSENTED` leaves the status unchanged.

**Finalization.** Finalizing is accepted from `REGISTRY_CONFIRMED`, `NOK_CONSENTED` or `DOCUMENT_DEFICIENT`, and from any other status yields `ERR_AUTHORIZATION_NOT_FINALIZABLE`. Where `documentation_complete` is true, the packet moves to `AUTHORIZED` and the acting specialist is recorded in `finalized_by_user_id`; from `NOK_CONSENTED` this additionally requires that the finalizer differ from `consent_recorded_by_user_id`, while from `REGISTRY_CONFIRMED` that check is vacuous because no consent-taker exists. Where `documentation_complete` is false and the packet sits in `NOK_CONSENTED`, finalization opens the deficiency cycle instead: the packet moves `NOK_CONSENTED → DOCUMENT_DEFICIENT` — the state change **is** recorded — and the caller nonetheless receives `ERR_AUTHORIZATION_DOCUMENTATION_INCOMPLETE`.

**Rescission, and the five-hop cascade it drives.** Consent remains revocable after authorization. When an `OBJECTION` is recorded on a packet that is `AUTHORIZED`, whose `authorization_basis` is `LEGAL_NEXT_OF_KIN`, and whose objecting relative's rank is numerically lower than the packet's `consenting_rank`, the packet moves `AUTHORIZED → RESCINDED` with `rescinded_reason` set to `HIGHER_RANK_OBJECTION`. (`rescinded_reason` admits one other declared value, `DOCUMENT_FRAUD`, reserved for administratively voided packets; it defaults to null and no workflow in this specification sets it.) That is hop one. Hop two moves the referral `CONVERTED → NOT_CONVERTED`, decrements the hospital's `converted_donor_count` by one, and moves the donor case's `allocation_status` to `CLOSED` with `closed_reason` `AUTHORIZATION_RESCINDED`, which drives `case_posture` to `FROZEN`. Hop three, because the case closed, takes every organ of the case whose status is `PENDING_EVAL`, `ALLOCATABLE`, `OFFERING` or `ACCEPTED` to `NON_TRANSPLANTABLE` with `nontransplantable_reason` `AUTHORIZATION_RESCINDED`, clears each one's `accepted_offer_id` to null, and refreshes the case's `organs_nontransplantable_count`. Hop four, because those organs left `OFFERING` and `ACCEPTED`, takes each of their match runs still in `OPEN` to `CLOSED` with `closed_reason` `CASE_CLOSED`, and takes every offer on those runs whose status is `QUEUED`, `PENDING` or `ACCEPTED` to `BYPASSED` with `bypass_reason` `CASE_CLOSED`, resetting each run's `pending_offer_count` to zero and its `slots_free` to that run's `primary_offer_slots`. Hop five, because the case closed, takes every recovery operation of the case whose status is `SCHEDULED` to `CANCELLED` with `cancelled_reason` `CASE_CLOSED`, which decrements the booking team's `booked_or_minutes` by that operation's `or_minutes` and its `scheduled_operation_count` by one. Note the tail effect on disposition: an organ made non-transplantable by rescission may **not** afterwards be referred to research or tissue, because no research authorization exists for it.

### 3.4. Donor Case Conversion and Physiologic Management

A `DonorCoordinator` converts a referral into a donor case by supplying the `referral_id`, the `authorization_id` of the packet that legally permits recovery, and a `donor_code` between 3 and 16 characters that is printed on labels and must be unique across all donor cases. Four gates guard the conversion. The referral must be in `AUTH_PENDING` and its screening must be in `CLEARED`, otherwise `ERR_SCREENING_NOT_CLEARED`. The named authorization must be in `AUTHORIZED`, otherwise `ERR_AUTHORIZATION_NOT_GRANTED`. The named authorization must reference the same referral as the case, and the screening consulted must belong to that referral, otherwise `ERR_AUTHORIZATION_REFERRAL_MISMATCH`. And the screening's `absolute_contraindication` must be false, otherwise `ERR_ABSOLUTE_CONTRAINDICATION` — this is the gate that catches a serology result filed after clearance.

On success the referral advances `AUTH_PENDING → CONVERTED` and the hospital's `converted_donor_count` increases by one. The new case starts with `physiologic_status` at `STABILIZING`, `allocation_status` at `NOT_STARTED` and `case_posture` at `OPEN`; its `viability_index`, `dmg_bundle_met_count`, `observation_count`, `organ_count`, `organs_accepted_count`, `organs_recovered_count` and `organs_nontransplantable_count` all start at zero; its `closed_reason` starts null; and `risk_tier_snapshot` is pinned from the screening's `risk_tier` at this moment, taking the value `STANDARD` or `INCREASED_RISK`, and never changes thereafter. Cases may be listed with optional filters on `referral_id`, `authorization_id` and `case_posture`, which serves as the reverse lookup from either parent.

**Charting an observation.** The coordinator charts vitals with the `recorded_at` instant they were taken, `map_mmhg` as mean arterial pressure from 0 through 200, `pao2_fio2_ratio` as the oxygenation ratio from 0 through 600, `sodium` as serum sodium in millimoles per litre from 100 through 200, `urine_output_ml_per_kg_hr` from 0 through 20, `pressor_count` as the number of vasopressor agents infusing from 0 through 5, and an optional `cardiac_arrest` boolean defaulting to false. The `recorded_at` instant must not be after the logical clock, otherwise `ERR_OBSERVATION_IN_FUTURE`. The charting operator is recorded in `recorded_by_user_id`. Charting is one of the mutations blocked when the case is frozen.

**The viability index, in four steps.** Oxygenation is scored on `pao2_fio2_ratio` alone: a ratio of at least 300 scores 40 points, otherwise a ratio of at least 200 scores 30, otherwise a ratio of at least 100 scores 15, otherwise 0. Haemodynamics starts from `map_mmhg`: a pressure of at least 70 gives a base of 35 points, otherwise at least 60 gives 25, otherwise at least 50 gives 10, otherwise 0. A pressor penalty is then computed as five points per infusing agent, capped at 15 — the smaller of 15 and five times `pressor_count` — and subtracted from the base, with the result floored at zero so haemodynamics never contributes a negative amount. Metabolic scoring combines two inputs: sodium contributes 15 points when it lies at or between 135 and 155 inclusive and 5 points otherwise; urine output contributes 10 points at 1.0 or above, 5 points at 0.5 or above, and 0 below that. The three components are added and clamped into the range 0 through 100 to give the observation's `viability_index_snapshot`; and if this observation records a cardiac arrest, the snapshot is forced to 0 outright.

**The donor management goal bundle.** Independently of the index, each observation carries `dmg_bundle_met`, which is true only when **all five** bounds hold simultaneously: `map_mmhg` is at least 60, `pao2_fio2_ratio` is at least 300, `sodium` lies at or between 135 and 155 inclusive, `urine_output_ml_per_kg_hr` is at least 0.5, and `pressor_count` is at most 1.

**Projecting onto the case.** The case always takes the index of its **latest** observation, where latest means the greatest `recorded_at`, breaking a tie by the greatest `created_at`. That snapshot becomes the case's `viability_index`. The physiologic dimension is then re-derived from the latest observation: if it recorded a cardiac arrest, `physiologic_status` becomes `LOST`; otherwise an index of at least 70 gives `OPTIMIZED`, an index of at least 40 gives `STABILIZING`, and anything lower gives `DECOMPENSATING`. The case's `dmg_bundle_met_count` is refreshed to the number of its observations whose `dmg_bundle_met` is true, and `observation_count` to the total number of its observations; both aggregate over **all** observations of the case, not merely the latest.

**The decompensation cascade.** When a new observation drops a case from `physiologic_status` `OPTIMIZED` to `DECOMPENSATING`, four hops follow. Hop one sets the case's `viability_index` to the new snapshot and `physiologic_status` to `DECOMPENSATING`. Hop two re-derives `case_posture` from `OPEN` to `RESTRICTED`. Hop three, precisely because the posture became restricted, takes every organ on the case whose `organ_type` is `HEART`, `LUNG_LEFT` or `LUNG_RIGHT` and whose status is `ALLOCATABLE` or `OFFERING`, sets its `viability_hold` to true and returns its status to `PENDING_EVAL`; abdominal organs are untouched. Hop four, because those thoracic organs left `OFFERING`, takes each of their match runs still in `OPEN` to `CLOSED` with `closed_reason` `VIABILITY_HOLD`, and takes every offer on those runs whose status is `QUEUED` or `PENDING` to `BYPASSED` with `bypass_reason` `VIABILITY_HOLD`, resetting each run's `pending_offer_count` to zero and its `slots_free` to that run's `primary_offer_slots`.

**Recovering from decompensation.** A subsequent observation whose snapshot reaches at least 70 moves the case `DECOMPENSATING → OPTIMIZED` and returns `case_posture` from `RESTRICTED` to `OPEN`. Every organ on the case whose `viability_hold` is true has that flag reset to false — but organ status is deliberately **not** auto-restored: each held organ remains in `PENDING_EVAL` until a director explicitly re-evaluates it.

**Donor loss.** An observation recording `cardiac_arrest` as true drives the case from `STABILIZING`, `OPTIMIZED` or `DECOMPENSATING` to `physiologic_status` `LOST`, which is terminal for that dimension, and sets `viability_index` to 0. Unless the case has already reached `allocation_status` `RECOVERED`, the allocation dimension also moves to `CLOSED` with `closed_reason` `DONOR_LOST`. Either way `case_posture` becomes `FROZEN`. Every organ of the case whose status is `PENDING_EVAL`, `ALLOCATABLE`, `OFFERING` or `ACCEPTED` moves to `NON_TRANSPLANTABLE` with `nontransplantable_reason` `VIABILITY_FAILURE` and its `accepted_offer_id` cleared to null, and each of those organs' match runs still in `OPEN` moves to `CLOSED` with `closed_reason` `CASE_CLOSED`, its `QUEUED` and `PENDING` offers moving to `BYPASSED` with `bypass_reason` `CASE_CLOSED`.

### 3.5. Organ Registration, Evaluation and Match Run Generation

The `DonorCoordinator` registers each recoverable organ on the case by naming its `organ_type`, one of `HEART`, `LUNG_LEFT`, `LUNG_RIGHT`, `LIVER`, `KIDNEY_LEFT`, `KIDNEY_RIGHT`, `PANCREAS` or `INTESTINE`, and a case may carry each type at most once. Registration sets the organ's `cit_limit_minutes` from the cold-ischemic ceiling for its type and starts it in status `PENDING_EVAL` with `viability_hold` false, `accepted_offer_id`, `cross_clamp_at`, `transport_asset_id`, `transport_mode`, `transport_depart_at`, `transport_arrive_at`, `transit_minutes`, `implant_prep_minutes`, `projected_cold_ischemic_minutes`, `projected_cit_margin_minutes`, `nontransplantable_reason`, `research_protocol_code` and `tissue_processor_code` all null. The case's `organ_count` increases by one. The cold-ischemic ceilings are four hours for a `HEART`, six hours each for `LUNG_LEFT` and `LUNG_RIGHT`, twelve hours each for a `LIVER` and a `PANCREAS`, eight hours for an `INTESTINE`, and eighteen hours each for `KIDNEY_LEFT` and `KIDNEY_RIGHT`, all expressed internally in whole minutes. Organs may be listed with optional filters on `donor_case_id`, `accepted_offer_id`, `transport_asset_id` and `status`.

**Evaluation.** A `MedicalDirector` rules on an organ by submitting a `decision` of either `ALLOCATABLE` or `NON_TRANSPLANTABLE`, and may accompany a non-transplantable ruling with a `nontransplantable_reason` drawn from `AUTHORIZATION_RESCINDED`, `VIABILITY_FAILURE`, `NO_ACCEPTING_CENTER` or `ANATOMIC_ANOMALY`; when no reason is supplied, `ANATOMIC_ANOMALY` is stored. Evaluation is accepted only from status `PENDING_EVAL`, otherwise `ERR_ORGAN_NOT_EVALUABLE`. Declaring an organ `ALLOCATABLE` additionally requires `viability_hold` to be false — a still-held organ yields `ERR_VIABILITY_HOLD_ACTIVE` — and requires the case's posture to be `OPEN`. Declaring an organ `NON_TRANSPLANTABLE` requires only that the case not be frozen; on success the case's `organs_nontransplantable_count` increases by one.

**Generating a national match run.** An `AllocationSpecialist` opens allocation for an organ by generating a match run against the national candidate sequence. The request carries the `expected_organ_version` of §2.7, a `candidates` array, and an optional `primary_offer_slots` integer from 1 through 3 declaring how many offers may sit pending at once — primary plus backups — which defaults to 2. Each candidate entry supplies its `sequence_position` in the national match sequence, which must be at least 1, the `center_code` of the transplant centre holding the candidate, the `candidate_code` identifying the candidate at that centre, and an optional `acceptance_clock_minutes` from 5 through 240 stating how long that centre gets to answer once its offer is promoted, defaulting to 60. An empty `candidates` array is rejected with `ERR_EMPTY_MATCH_RUN`; positions that repeat or that are not contiguous starting at 1 are rejected with `ERR_INVALID_SEQUENCE`. The organ must be in `ALLOCATABLE` or `OFFERING`, otherwise `ERR_ORGAN_NOT_ALLOCATABLE`, and a thoracic organ on a restricted case is refused with `ERR_POSTURE_RESTRICTED`.

Generation creates one offer per candidate in status `QUEUED`, sets the run's `candidate_count` to the number created, stamps `generated_at` from the logical clock, assigns `run_number` as one more than the highest existing run number on that organ — so the first run on an organ is number 1 — records the `organ_id` it allocates, opens the run in status `OPEN` with `closed_reason` null, and increments the organ's `version` by one. If the organ already had a run in `OPEN`, that prior run moves `OPEN → SUPERSEDED` with `closed_reason` `SUPERSEDED_BY_NEW_RUN`, and its offers in `QUEUED` or `PENDING` move to `BYPASSED`; note carefully that a superseded run's bypassed offers take `bypass_reason` **null** — none of `PEER_ACCEPTED`, `CASE_CLOSED` or `VIABILITY_HOLD` is used for a supersede. This legitimate supersede is precisely why match-run generation is guarded by the organ's version rather than by a state precondition. Generation then immediately runs the promotion selector described in §3.6. The organ moves `ALLOCATABLE → OFFERING` as soon as at least one offer is promoted, and the case's `allocation_status` advances from `NOT_STARTED` to `MATCH_RUN_OPEN` on the first run generated on any organ of the case and then onward to `OFFERS_IN_FLIGHT` once a pending offer exists. Generating a run requires the case's posture not to be `FROZEN`.

### 3.6. Offer Sequencing, Acceptance Clocks and Compensating Withdrawal

**The promotion selector** is the single mechanism that decides which candidates hold live offers. It runs at match-run generation, whenever a specialist advances a run, and immediately after any decline, expiry or acceptance withdrawal on a run. It proceeds in five steps over the offers of exactly one run; offers on superseded or closed runs are never considered.

First, on an advance, the expiry sweep: every offer of this run whose status is `PENDING` and whose `expires_at` has been reached by the logical clock becomes `EXPIRED`. The boundary is inclusive — an offer whose `expires_at` equals the current clock instant **is** swept — and each sweep decrements the run's `pending_offer_count` by one and increments its `slots_free` by one. Second, the eligibility filter: the candidate pool is exactly those offers of this run whose status is `QUEUED`. No other status is eligible; a `BYPASSED` offer re-enters only after being restored to `QUEUED`. Third, ranking: candidates are ordered by `sequence_position` ascending, with `created_at` ascending as a tie-break that is unreachable while positions are unique within a run; the resource `id` is never consulted. Fourth, the fill: while the run's `pending_offer_count` is below its `primary_offer_slots` and the pool is non-empty, the ranked head is taken, its status set to `PENDING`, its `offered_at` stamped from the logical clock, its `expires_at` set to that instant plus its own `acceptance_clock_minutes`, the run's `pending_offer_count` incremented by one and its `slots_free` decremented by one. Fifth, the empty-pool fallback: if the pool was empty **and** the run's `pending_offer_count` is zero after the sweep, the run moves `OPEN → EXHAUSTED` with `closed_reason` `CANDIDATES_EXHAUSTED`, the organ returns `OFFERING → ALLOCATABLE`, the case returns `allocation_status` `OFFERS_IN_FLIGHT → MATCH_RUN_OPEN`, and the response reports a `promoted_count` of 0. If the pool is empty but some offer is still `PENDING`, the run simply stays `OPEN`.

Advancing a run requires it to be in `OPEN`, otherwise `ERR_MATCH_RUN_NOT_OPEN`. A run may be read directly, exposing its `pending_offer_count` and `slots_free`, and its offers may be listed by reverse lookup with an optional `status` filter.

**Recording a centre's response.** The specialist submits a `decision` of `ACCEPT`, `DECLINE` or `WITHDRAW_ACCEPTANCE`, optionally with a `decline_reason` from `DONOR_QUALITY`, `RECIPIENT_UNAVAILABLE`, `LOGISTICS` or `SIZE_MISMATCH`, and optionally with an `increased_risk_ack` boolean defaulting to false. The offer addressed must have a `match_run_id` equal to the run named in the path, otherwise `ERR_OFFER_RUN_MISMATCH`. An `ACCEPT` or a `DECLINE` requires the offer to be in `PENDING`, and a `WITHDRAW_ACCEPTANCE` requires it to be in `ACCEPTED`; any other combination yields `ERR_OFFER_NOT_PENDING`. Whatever the decision, `responded_at` is stamped from the logical clock and the acting specialist is recorded in `responded_by_user_id`.

An `ACCEPT` requires that the acceptance clock has not run out — the logical clock must be strictly before the offer's `expires_at`, and reaching or passing it yields `ERR_ACCEPTANCE_CLOCK_ELAPSED`. It also enforces the increased-risk protocol: when the donor case's `risk_tier_snapshot` is `INCREASED_RISK`, the accepting centre must have set `increased_risk_ack` to true, and omitting it yields `ERR_INCREASED_RISK_ACK_REQUIRED`; a `STANDARD` donor needs no acknowledgement. On success the offer moves `PENDING → ACCEPTED`, the run's `pending_offer_count` decreases by one, the organ moves `OFFERING → ACCEPTED` with its `accepted_offer_id` set to the accepting offer, the run moves `OPEN → CLOSED` with `closed_reason` `ACCEPTED`, and every other offer on the run whose status is `QUEUED` or `PENDING` moves to `BYPASSED` with `bypass_reason` `PEER_ACCEPTED`. The run's `pending_offer_count` settles at zero and its `slots_free` at its `primary_offer_slots`. The case's `allocation_status` advances `OFFERS_IN_FLIGHT → ALLOCATED` and its `organs_accepted_count` increases by one.

A `DECLINE` requires a non-null `decline_reason`. The offer moves `PENDING → DECLINED`, which is terminal for the offer, the run's `pending_offer_count` decreases by one and its `slots_free` increases by one, and the promotion selector immediately re-runs on that run, promoting the next queued candidate if one exists.

**Withdrawal is the compensating action** and it unwinds an acceptance exactly. It requires the offer to be in `ACCEPTED`, the organ to name that offer in its `accepted_offer_id`, and the organ still to be in `ACCEPTED` — that is, not yet recovered. The offer moves `ACCEPTED → WITHDRAWN`, which is terminal for the offer. The organ returns `ACCEPTED → OFFERING` and its `accepted_offer_id` is cleared to null. The run returns `CLOSED → OPEN` and its `closed_reason` is cleared to null. Every offer on that run whose status is `BYPASSED` **and** whose `bypass_reason` is `PEER_ACCEPTED` is restored to `QUEUED` with `bypass_reason` cleared to null — bypasses caused by a case closure, a viability hold or a supersede are **not** restored. The promotion selector then re-runs, bringing `pending_offer_count` back up to the smaller of `primary_offer_slots` and the number of queued offers now available. The case's `allocation_status` returns `ALLOCATED → OFFERS_IN_FLIGHT` and its `organs_accepted_count` decreases by one.

### 3.7. Recovery Surgery, Cross-Clamp and Transport Dispatch

Surgical capacity is registered ahead of time. An `OpoAdmin` creates each recovery team with a `team_code` of 2 to 12 characters that is unique across teams, a `specialty` of `THORACIC`, `ABDOMINAL` or `MULTIORGAN`, and a `turnaround_buffer_minutes` from 0 through 480 that defaults to 90 and is applied symmetrically around every booked window when availability is tested. A new team starts with `booked_or_minutes` and `scheduled_operation_count` at zero. Transport capacity is registered the same way: each transport asset has an `asset_code` of 2 to 12 characters unique across assets, a `mode` of `GROUND`, `FIXED_WING` or `HELICOPTER`, and a `concurrent_leg_capacity` from 1 through 5 declaring how many organ legs it may carry over an overlapping window, defaulting to 1; `active_leg_count` starts at zero and always reflects the number of organs assigned to that asset whose status is `RECOVERED`, that is, in transit.

**Booking the operating room.** A `RecoveryLogistics` operator books a window on the donor case by naming the `recovery_team_id` and the window's `or_start_at` and `or_end_at`. The end must fall strictly after the start, otherwise `ERR_INVALID_TIME_WINDOW`. The case must have at least one organ in status `ACCEPTED`, otherwise `ERR_NO_ACCEPTED_ORGANS`. The team's specialty must cover **every** organ type in that accepted set: a `THORACIC` team covers `HEART`, `LUNG_LEFT` and `LUNG_RIGHT`; an `ABDOMINAL` team covers the remaining types; a `MULTIORGAN` team covers all of them. A gap in coverage yields `ERR_TEAM_SPECIALTY_MISMATCH`.

Team availability is then tested with the buffer applied to both sides of each existing window. The requested window conflicts with an existing operation of the same team, whose status is `SCHEDULED` or `COMPLETED`, when the new start falls strictly before that operation's end plus the buffer **and** that operation's start falls strictly before the new end plus the buffer. Both comparisons are strict, so a window beginning exactly the buffer's worth of minutes after an existing window ends is accepted. Operations already `CANCELLED` are excluded from the test entirely. A conflict yields `ERR_TEAM_WINDOW_CONFLICT`.

On success the operation is created in status `SCHEDULED` with `cross_clamp_at` and `cancelled_reason` null, its `or_minutes` computed as the whole minutes from `or_start_at` to `or_end_at`, and its `organ_types_covered` pinned to the `organ_type` values of the case's accepted organs as they stand at scheduling time. The team's `booked_or_minutes` increases by that `or_minutes` and its `scheduled_operation_count` by one. Operations may be listed with optional filters on `donor_case_id`, `recovery_team_id` and `status`.

**Cross-clamp.** Recording aortic cross-clamp completes the operation. The operation must be in `SCHEDULED`, otherwise `ERR_OPERATION_NOT_SCHEDULED`; the case must not be frozen; and at least one organ of the case must be in `ACCEPTED`. The operation moves `SCHEDULED → COMPLETED`, its `cross_clamp_at` stamped from the logical clock, and the team's `scheduled_operation_count` decreases by one while its `booked_or_minutes` stays **unchanged** — a completed window remains on the ledger, because the theatre time was genuinely consumed. Every organ of the case in status `ACCEPTED` moves to `RECOVERED` with the operation's `cross_clamp_at` copied onto it, and the case's `organs_recovered_count` is refreshed, counting organs whose status is `RECOVERED`, `TRANSPLANTED` or `DISCARDED`. The case's `allocation_status` advances `ALLOCATED → RECOVERED`.

**Cancellation** is the compensating half of the operating-room ledger. Cancelling requires the operation to be in `SCHEDULED`; it moves `SCHEDULED → CANCELLED` with `cancelled_reason` `LOGISTICS_WITHDRAWN`, decreases the team's `booked_or_minutes` by that operation's `or_minutes`, and decreases its `scheduled_operation_count` by one. A cancellation driven instead by the case closing carries `cancelled_reason` `CASE_CLOSED` and releases the same ledger amounts.

**Dispatching transport.** A `RecoveryLogistics` operator dispatches a recovered organ by naming the `transport_asset_id` carrying it, the `transport_mode` of the leg — `GROUND`, `FIXED_WING` or `HELICOPTER` — and the leg's scheduled `transport_depart_at` and `transport_arrive_at` at the accepting centre. The organ must be in status `RECOVERED`, otherwise `ERR_ORGAN_NOT_RECOVERED`, which guarantees its `cross_clamp_at` is already set. The arrival must fall strictly after the departure, and the departure must not fall before the organ's `cross_clamp_at`; either violation yields `ERR_INVALID_TIME_WINDOW`.

**Projecting cold ischemic time** is resolved in a deliberately pinned single pass, because the implantation prep allowance depends on the remaining margin while the remaining margin depends on the prep allowance. First, the elapsed cold time so far is the whole minutes from the organ's `cross_clamp_at` to `transport_depart_at`, and `transit_minutes` is the whole minutes from `transport_depart_at` to `transport_arrive_at`, both truncated downward. Second, a provisional margin is computed as the organ's `cit_limit_minutes` less the elapsed minutes, less the transit minutes, less a base prep allowance of 45 minutes; and the prep tier is selected from that **provisional** margin — a margin of at least 120 minutes selects standard prep at 45 minutes, otherwise a margin of at least 60 minutes selects expedited prep at 30 minutes, otherwise crash prep at 20 minutes — and the chosen value is stored as `implant_prep_minutes`. Third, `projected_cold_ischemic_minutes` is the elapsed minutes plus `transit_minutes` plus the selected `implant_prep_minutes`; the tier is **not** re-selected from this final figure, exactly one pass is performed, and no fixed point is sought. Fourth, `projected_cit_margin_minutes` is the organ's `cit_limit_minutes` less `projected_cold_ischemic_minutes`. The gate then rejects the dispatch only when `projected_cold_ischemic_minutes` **strictly exceeds** `cit_limit_minutes`, with `ERR_COLD_ISCHEMIC_LIMIT_EXCEEDED`; a projection exactly equal to the ceiling is accepted.

**Asset capacity.** Before the dispatch is committed, the system counts the organs already assigned to the named asset whose status is `RECOVERED` or `TRANSPLANTED` and whose leg overlaps the requested leg on **closed** intervals — that is, where the new departure is at or before the existing arrival and the existing departure is at or before the new arrival, so legs that merely touch at an endpoint do collide. When that count has already reached the asset's `concurrent_leg_capacity`, the dispatch is rejected with `ERR_ASSET_CAPACITY_EXCEEDED`. On success the asset's `active_leg_count` is refreshed. Dispatch is also one of the mutations blocked when the case is frozen.

### 3.8. Final Disposition and Recertification Reporting

The `MedicalDirector` closes the book on each organ by recording a `disposition` of `TRANSPLANTED`, `DISCARDED`, `RESEARCH_REFERRED` or `TISSUE_REFERRED`. All four target states are terminal for the organ. An organ in `RECOVERED` may be dispositioned `TRANSPLANTED` or `DISCARDED`. An organ in `NON_TRANSPLANTABLE` may be referred onward: `RESEARCH_REFERRED` requires a non-null `research_protocol_code`, which is stored on the organ, and `TISSUE_REFERRED` requires a non-null `tissue_processor_code`, likewise stored. Neither referral is permitted when the organ's `nontransplantable_reason` is `AUTHORIZATION_RESCINDED`, because a rescinded authorization grants no research or tissue permission. A disposition that does not match the organ's status, that omits its required code, or that runs into the rescission bar is rejected with `ERR_DISPOSITION_NOT_ALLOWED`. Uniquely among case-child mutations, recording a disposition is permitted even when the case's posture is `FROZEN`, so that organs stranded by a closure can still be accounted for.

When a disposition leaves **every** organ of the case in one of its terminal states — `TRANSPLANTED`, `DISCARDED`, `RESEARCH_REFERRED` or `TISSUE_REFERRED` — the case's `allocation_status` advances `RECOVERED → CLOSED` with `closed_reason` `RECOVERY_COMPLETE`, and `case_posture` becomes `FROZEN`. The case's `organs_recovered_count` and `organs_nontransplantable_count` are refreshed after every disposition, the former counting organs in `RECOVERED`, `TRANSPLANTED` or `DISCARDED` and the latter counting organs in `NON_TRANSPLANTABLE`, `RESEARCH_REFERRED` or `TISSUE_REFERRED`.

**The recertification report** is a computed read against one hospital and persists nothing. It accepts an optional `window_days` integer, defaulting to 365, and an optional `basis` of `CLINICAL_TRIGGER` or `DEATH_NOTE`, defaulting to `CLINICAL_TRIGGER`. The reporting window is half-open: `window_end` is the current logical clock instant and is **exclusive**, while `window_start` is that instant less `window_days` days and is **inclusive**. The referrals in scope are exactly the hospital's referrals whose `referred_at` is at or after `window_start` and strictly before `window_end`.

From that scope the report derives, alongside the echoed `hospital_partner_id`, `window_days`, `basis`, `window_start` and `window_end`: an `eligible_referral_count`, being the number of in-scope referrals whose `ventilated` is true, which is the imminent-death denominator; a `timely_referral_count`, being the number of in-scope referrals that are both ventilated and timely; a `cleared_referral_count`, being the number of in-scope referrals whose `status` is `AUTH_PENDING`, `CONVERTED` or `NOT_CONVERTED`; a `converted_referral_count`, being the number whose `status` is `CONVERTED`; and a `transplanted_organ_count`, being the number of organs in status `TRANSPLANTED` whose donor case was converted from an in-scope referral. On the `CLINICAL_TRIGGER` basis, timeliness is read from each referral's stored `timeliness_flag`. On the `DEATH_NOTE` basis, timeliness is instead re-derived from `audit_lag_minutes` against the hospital's window, and referrals whose `audit_lag_minutes` is null are excluded from **both** the timely count and the eligible count.

Three ratios follow. The report's `timely_referral_rate` is null when `eligible_referral_count` is zero, and otherwise one hundred multiplied by the windowed timely count, divided by `eligible_referral_count`, rounded half up to two decimal places. The `conversion_rate` is null when `cleared_referral_count` is zero, and otherwise one hundred multiplied by `converted_referral_count`, divided by `cleared_referral_count`, rounded half up to two decimal places. The `organs_per_donor` figure is null when `converted_referral_count` is zero, and otherwise `transplanted_organ_count` divided by `converted_referral_count`, rounded half up to two decimal places.

The `recertification_tier` is then derived in a fixed order. If `eligible_referral_count` is zero, the tier is `INSUFFICIENT_DATA`. Otherwise, if the windowed `timely_referral_rate` is at least 75.00 **and** the `conversion_rate` — treated as zero when null — is at least 65.00 **and** `organs_per_donor` — likewise treated as zero when null — is at least 3.00, the tier is `PASS`. Otherwise, if the windowed `timely_referral_rate` is at least 60.00, the tier is `PROBATION`. Otherwise it is `FAIL`. Because this windowed denominator counts only ventilated referrals inside the half-open window while the hospital's persisted lifetime rate counts every referral it ever placed, the same hospital can quite legitimately carry a `partner_posture` of `GOOD_STANDING` while its `recertification_tier` reads `FAIL`.

## 4. Endpoint Definitions

Operations that bring a new, independently addressable resource into existence — a hospital partner, a recovery team, a transport asset, a death referral, an eligibility screening, a serology result, an authorization, a next-of-kin contact, a donor case, a physiologic observation, an organ, a match run — return `201 Created`. Operations that act upon a resource that already exists, including every state-advancing action, every document filing, every ruling and every ledger adjustment, return `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/opo/hospital-partners` | Register a referring hospital with its clinical trigger policy and timely-referral window | OpoAdmin |
| GET | `/opo/hospital-partners/{id}` | Read one hospital partner including its lifetime timeliness counters and posture | OpoAdmin, ReferralCoordinator, MedicalDirector, HospitalReferralClerk |
| GET | `/opo/hospital-partners/{id}/performance` | Computed read of windowed recertification metrics; nothing is persisted | OpoAdmin, MedicalDirector |
| POST | `/opo/recovery-teams` | Register a surgical recovery team with its specialty and turnaround buffer | OpoAdmin |
| GET | `/opo/recovery-teams/{id}` | Read one recovery team including its OR-minutes ledger | OpoAdmin, RecoveryLogistics, MedicalDirector |
| POST | `/opo/transport-assets` | Register a transport asset with its carriage mode and concurrent leg capacity | OpoAdmin |
| GET | `/opo/transport-assets/{id}` | Read one transport asset including its active leg count | OpoAdmin, RecoveryLogistics |
| POST | `/opo/death-referrals` | Record a hospital death referral call and score timeliness on both bases | HospitalReferralClerk, ReferralCoordinator |
| GET | `/opo/death-referrals/{id}` | Read one death referral with its lag minutes and timeliness flag | OpoAdmin, ReferralCoordinator, MedicalDirector, AuthorizationSpecialist, DonorCoordinator, HospitalReferralClerk |
| GET | `/opo/death-referrals` | List death referrals, filterable by hospital, status and timeliness flag | OpoAdmin, ReferralCoordinator, MedicalDirector |
| POST | `/opo/death-referrals/{id}/screenings` | Open the eligibility screening for a received referral | ReferralCoordinator |
| GET | `/opo/death-referrals/{id}/screenings` | Reverse lookup of the screening for a referral; array of length 0 or 1 | OpoAdmin, ReferralCoordinator, MedicalDirector, SerologyLab, DonorCoordinator |
| GET | `/opo/eligibility-screenings/{id}` | Read one eligibility screening including risk score, tier, variant applied and version | OpoAdmin, ReferralCoordinator, MedicalDirector, SerologyLab, DonorCoordinator |
| POST | `/opo/eligibility-screenings/{id}/risk-assessment` | Submit or resubmit the behavioral risk assessment; guarded on the screening version | ReferralCoordinator |
| POST | `/opo/eligibility-screenings/{id}/serology-results` | File a serologic laboratory result against the screening | SerologyLab |
| GET | `/opo/eligibility-screenings/{id}/serology-results` | Reverse lookup of serology results for a screening | OpoAdmin, ReferralCoordinator, MedicalDirector, SerologyLab |
| POST | `/opo/eligibility-screenings/{id}/request-info` | Bounce the screening back to the coordinator for more behavioral history | MedicalDirector |
| POST | `/opo/eligibility-screenings/{id}/decision` | Rule the screening cleared or ruled out, under segregation of duties | MedicalDirector |
| POST | `/opo/death-referrals/{id}/authorizations` | Open the authorization packet; the registry hit selects the branch at creation | AuthorizationSpecialist |
| GET | `/opo/death-referrals/{id}/authorizations` | Reverse lookup of authorizations for a referral | OpoAdmin, AuthorizationSpecialist, MedicalDirector, DonorCoordinator |
| GET | `/opo/authorizations/{id}` | Read one authorization packet including basis, consenting rank, documentation completeness and version | OpoAdmin, AuthorizationSpecialist, MedicalDirector, DonorCoordinator |
| POST | `/opo/authorizations/{id}/nok-contacts` | Record a next-of-kin contact attempt against the statutory hierarchy | AuthorizationSpecialist |
| GET | `/opo/authorizations/{id}/nok-contacts` | Reverse lookup of next-of-kin contacts for an authorization | OpoAdmin, AuthorizationSpecialist, MedicalDirector |
| POST | `/opo/authorizations/{id}/documents` | File a document into the packet and recompute documentation completeness | AuthorizationSpecialist |
| POST | `/opo/authorizations/{id}/finalize` | Finalize the authorization packet, under segregation of duties | AuthorizationSpecialist |
| POST | `/opo/donor-cases` | Convert a cleared, authorized referral into a donor case | DonorCoordinator |
| GET | `/opo/donor-cases/{id}` | Read one donor case with both status dimensions, derived posture, viability index and organ counters | OpoAdmin, DonorCoordinator, MedicalDirector, AllocationSpecialist, RecoveryLogistics |
| GET | `/opo/donor-cases` | List donor cases, filterable by referral, authorization and posture | OpoAdmin, DonorCoordinator, MedicalDirector, AllocationSpecialist |
| POST | `/opo/donor-cases/{id}/observations` | Chart a physiologic observation and recompute the viability index and physiologic dimension | DonorCoordinator |
| GET | `/opo/donor-cases/{id}/observations` | Reverse lookup of physiologic observations for a case | OpoAdmin, DonorCoordinator, MedicalDirector |
| POST | `/opo/donor-cases/{id}/organs` | Register a recoverable organ on the donor case | DonorCoordinator |
| GET | `/opo/organs/{id}` | Read one organ including its cold-ischemic projection fields and version | OpoAdmin, DonorCoordinator, MedicalDirector, AllocationSpecialist, RecoveryLogistics |
| GET | `/opo/organs` | List organs, filterable by case, accepted offer, transport asset and status | OpoAdmin, DonorCoordinator, MedicalDirector, AllocationSpecialist, RecoveryLogistics |
| POST | `/opo/organs/{id}/evaluation` | Declare the organ allocatable or non-transplantable | MedicalDirector |
| POST | `/opo/organs/{id}/match-runs` | Generate a national match run with its sequenced candidate list; guarded on the organ version | AllocationSpecialist |
| GET | `/opo/organs/{id}/match-runs` | Reverse lookup of match runs for an organ | OpoAdmin, AllocationSpecialist, MedicalDirector |
| GET | `/opo/match-runs/{id}` | Read one match run including its pending offer count and free slots | OpoAdmin, AllocationSpecialist, MedicalDirector |
| GET | `/opo/match-runs/{id}/offers` | Reverse lookup of offers for a run, ordered by sequence position ascending | OpoAdmin, AllocationSpecialist, MedicalDirector |
| POST | `/opo/match-runs/{id}/offers/{offerId}/respond` | Record a transplant centre's acceptance, decline or withdrawal of acceptance | AllocationSpecialist |
| POST | `/opo/match-runs/{id}/advance` | Sweep elapsed acceptance clocks and refill the pending offer slots | AllocationSpecialist |
| POST | `/opo/donor-cases/{id}/recovery-operations` | Book an operating-room window for a recovery team | RecoveryLogistics |
| GET | `/opo/recovery-operations/{id}` | Read one recovery operation including its OR minutes and cross-clamp instant | OpoAdmin, RecoveryLogistics, MedicalDirector, DonorCoordinator |
| GET | `/opo/recovery-operations` | List recovery operations, filterable by case, team and status | OpoAdmin, RecoveryLogistics, MedicalDirector |
| POST | `/opo/recovery-operations/{id}/cross-clamp` | Record aortic cross-clamp, completing the operation and recovering every accepted organ | RecoveryLogistics |
| POST | `/opo/recovery-operations/{id}/cancel` | Cancel a scheduled operation, releasing the team's booked OR minutes | RecoveryLogistics |
| POST | `/opo/organs/{id}/transport` | Dispatch a recovered organ on a transport asset and project cold ischemic time | RecoveryLogistics |
| POST | `/opo/organs/{id}/disposition` | Record the final disposition of an organ | MedicalDirector |
| POST | `/_clock/set_current_utc` | Test-driving capability: set the logical clock to a supplied instant | OpoAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN_ROLE` | 403 Forbidden |
| `ERR_HOSPITAL_SCOPE_VIOLATION` | 403 Forbidden |
| `ERR_SEGREGATION_OF_DUTIES` | 403 Forbidden |
| `ERR_HOSPITAL_NOT_FOUND` | 404 Not Found |
| `ERR_REFERRAL_NOT_FOUND` | 404 Not Found |
| `ERR_SCREENING_NOT_FOUND` | 404 Not Found |
| `ERR_AUTHORIZATION_NOT_FOUND` | 404 Not Found |
| `ERR_DONOR_CASE_NOT_FOUND` | 404 Not Found |
| `ERR_ORGAN_NOT_FOUND` | 404 Not Found |
| `ERR_MATCH_RUN_NOT_FOUND` | 404 Not Found |
| `ERR_OFFER_NOT_FOUND` | 404 Not Found |
| `ERR_OPERATION_NOT_FOUND` | 404 Not Found |
| `ERR_TEAM_NOT_FOUND` | 404 Not Found |
| `ERR_ASSET_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_INVALID_PAGINATION` | 400 Bad Request |
| `ERR_DUPLICATE_KEY` | 409 Conflict |
| `ERR_REFERRAL_NOT_SCREENABLE` | 409 Conflict |
| `ERR_SCREENING_NOT_PENDING` | 409 Conflict |
| `ERR_RISK_ASSESSMENT_MISSING` | 409 Conflict |
| `ERR_INFO_REQUEST_LIMIT_REACHED` | 409 Conflict |
| `ERR_AUTHORIZATION_NOT_OPENABLE` | 409 Conflict |
| `ERR_AUTHORIZATION_NOT_CONTACTABLE` | 409 Conflict |
| `ERR_AUTHORIZATION_NOT_FINALIZABLE` | 409 Conflict |
| `ERR_NOK_HIERARCHY_VIOLATION` | 409 Conflict |
| `ERR_AUTHORIZATION_DOCUMENTATION_INCOMPLETE` | 422 Unprocessable Entity |
| `ERR_SCREENING_NOT_CLEARED` | 409 Conflict |
| `ERR_AUTHORIZATION_NOT_GRANTED` | 409 Conflict |
| `ERR_AUTHORIZATION_REFERRAL_MISMATCH` | 422 Unprocessable Entity |
| `ERR_ABSOLUTE_CONTRAINDICATION` | 422 Unprocessable Entity |
| `ERR_CASE_FROZEN` | 409 Conflict |
| `ERR_POSTURE_RESTRICTED` | 409 Conflict |
| `ERR_VIABILITY_HOLD_ACTIVE` | 409 Conflict |
| `ERR_OBSERVATION_IN_FUTURE` | 422 Unprocessable Entity |
| `ERR_REFERRAL_BEFORE_TRIGGER` | 422 Unprocessable Entity |
| `ERR_ORGAN_NOT_EVALUABLE` | 409 Conflict |
| `ERR_ORGAN_NOT_ALLOCATABLE` | 409 Conflict |
| `ERR_ORGAN_NOT_RECOVERED` | 409 Conflict |
| `ERR_EMPTY_MATCH_RUN` | 422 Unprocessable Entity |
| `ERR_INVALID_SEQUENCE` | 422 Unprocessable Entity |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_MATCH_RUN_NOT_OPEN` | 409 Conflict |
| `ERR_OFFER_NOT_PENDING` | 409 Conflict |
| `ERR_OFFER_RUN_MISMATCH` | 422 Unprocessable Entity |
| `ERR_ACCEPTANCE_CLOCK_ELAPSED` | 409 Conflict |
| `ERR_INCREASED_RISK_ACK_REQUIRED` | 422 Unprocessable Entity |
| `ERR_NO_ACCEPTED_ORGANS` | 409 Conflict |
| `ERR_TEAM_SPECIALTY_MISMATCH` | 422 Unprocessable Entity |
| `ERR_TEAM_WINDOW_CONFLICT` | 409 Conflict |
| `ERR_INVALID_TIME_WINDOW` | 422 Unprocessable Entity |
| `ERR_COLD_ISCHEMIC_LIMIT_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_ASSET_CAPACITY_EXCEEDED` | 409 Conflict |
| `ERR_OPERATION_NOT_SCHEDULED` | 409 Conflict |
| `ERR_DISPOSITION_NOT_ALLOWED` | 409 Conflict |
| `ERR_ALREADY_TERMINAL` | 409 Conflict |
