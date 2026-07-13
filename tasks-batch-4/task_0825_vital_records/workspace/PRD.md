# Vital Records Registration API — Product Requirements Document

## 1. Introduction

This document specifies the requirements for the Vital Records Registration API, the system of record for a state registrar office. The platform governs the full official lifecycle of birth, death, and fetal-death events: the electronic filing of records by hospitals and funeral homes, the medical certification of cause of death, the registrar's act of registration, and the downstream services that flow from a registered record — amendments and corrections, acknowledgments of paternity, issuance of certified and informational copies, international authentication of those copies, delayed and foreign registration proceedings, and periodic statistical reporting.

The domain is defined by a strict separation of duties. The facility that files a record cannot certify its cause of death, the physician who certifies cannot register the record, and the registrar who registers it performs neither of the other two acts. Members of the public interact only as requesters of copies and acknowledgments. Because vital records carry legal weight for decades, the system emphasizes auditability, conserved counters that must always reconcile, and defensive concurrency control so that a copy or a correction can never be minted from a stale view of the underlying record. All time-sensitive rules — statutory filing windows, rescission deadlines, and public-record aging — resolve against a single logical clock rather than wall-clock time, so that the office's deadlines are deterministic and reproducible.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, envelopes, and cross-cutting principles that apply across every endpoint.

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. If either header is missing, or `X-User-Role` is not one of the declared roles, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). If the role is recognized but not permitted to call the requested endpoint, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

The system recognizes exactly four roles: `StateRegistrar`, `FacilityFiler`, `MedicalCertifier`, and `Applicant`.

Two of these roles are tied to persisted entities, and their `X-User-ID` value is interpreted as an entity identity used for ownership checks:

- When `X-User-Role` is `FacilityFiler`, `X-User-ID` is the `id` of the acting `Facility`. Ownership checks on any vital event compare the event's `facility_id` to `X-User-ID`; a filer may file only events belonging to its own facility.
- When `X-User-Role` is `MedicalCertifier`, `X-User-ID` is the `id` of the acting `Certifier`. Ownership checks on a certification compare the certification's `certifier_id` to `X-User-ID`; a certifier may sign only its own certifications.

An ownership violation on these entity-backed actions is rejected with `ERR_NOT_OWNER` (HTTP 403).

The remaining two roles carry opaque identities. When `X-User-Role` is `StateRegistrar`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server neither compares it to an entity `id` nor requires it to resolve. When `X-User-Role` is `Applicant`, `X-User-ID` is likewise opaque; the server may record it — for example, an acknowledgment of paternity stores the creating actor's identifier in its `filed_by_user_id` field for audit — but never compares it to any entity's `id`.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter is the number of items to skip and defaults to 0.

Unless otherwise stated, list endpoints return resources sorted by their `created_at` timestamp in ascending order. Every list response includes `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope.

### 2.4. Common Resource Properties and the Logical Clock

Every resource in the system — facilities, certifiers, vital events, certifications, amendments, paternity acknowledgments, copy requests, apostille requests, delayed-registration packets, and statistics reports — carries a common set of system-managed fields:

- `id`: a server-minted UUID with no type prefix.
- `created_at`: an ISO 8601 UTC timestamp with three fractional digits, set when the resource is created.
- `updated_at`: an ISO 8601 UTC timestamp, refreshed on every mutation of the resource, including mutations caused indirectly by a cascade from another resource.
- `version`: an integer that starts at its initial value and increments by one on every mutation. It is the basis for optimistic concurrency control (§2.6).

All date and time reasoning uses a single logical clock rather than the host wall-clock. At server startup the clock reads exactly `2026-03-01T00:00:00Z`, and it holds that value until it is explicitly moved. An administrative capability lets a `StateRegistrar` set the clock to a supplied instant, provided in the `to_iso8601` field; every subsequent computation of elapsed time — filing lateness, record age, rescission deadlines, evidence thresholds, and reporting windows — is measured against the clock's current value.

### 2.5. Cascading Consistency and Conserved Counters

Several operations mutate more than one resource in a single atomic request. Whenever an operation changes a resource, that resource's `updated_at` is refreshed; where the entity participates in optimistic concurrency, its `version` is incremented as described per-workflow in §3. All cascades complete within the triggering request — there is no deferred reconciliation.

The system maintains a number of conserved counters that must always equal a recomputation from first principles:

- A `Facility` tracks `registered_count`, the number of vital events with that `facility_id` whose `status` is `REGISTERED` or `AMENDED`. It increases by one when a record is registered and decreases by one when a record is voided.
- A `Certifier` tracks `locked_certification_count`, the number of its certifications that have reached the `LOCKED` state through the registration cascade. It increases by one each time one of the certifier's certifications locks.
- A `VitalEvent` tracks `copies_issued_count`, the number of certified-copy requests against it whose `status` is `ISSUED`. It increases by one when a copy is issued and decreases by one for each issued copy reversed when the record is voided.
- A `VitalEvent` tracks `fees_collected_cents`, the sum of `fee_total_cents` across its issued copies. It increases by the copy's fee when a copy is issued and decreases by that same fee when an issued copy is reversed on void.
- A `VitalEvent` tracks `amendment_count`, the number of approved amendments applied to it, and a `MedicalCertification` tracks its own `amendment_count`, the number of medical amendments cascaded into it.

### 2.6. Optimistic Concurrency Control on the Record

Two operations write derived data onto a vital event based on a record the caller previously observed, and both are guarded by optimistic concurrency control keyed on the event's `version`.

Approving an amendment requires the request to carry `expected_vital_event_version`, the `version` of the target vital event the registrar last observed. If that value does not match the event's current `version` — because another amendment approval or a copy issuance has advanced the record since it was read — the approval is rejected with `ERR_STALE_EVENT_VERSION` (HTTP 412), so that a correction is never written over a record the registrar has not seen.

Issuing a certified copy likewise requires `expected_vital_event_version` matching the referenced event's current `version`. If the record has advanced since the requester last observed it, the issuance is rejected with `ERR_STALE_EVENT_VERSION` (HTTP 412), ensuring no copy is minted from an out-of-date view of the record.

These two operations are the only ones that accept `expected_vital_event_version`; no other endpoint takes a version field.

### 2.7. Cross-Reference Resolution and Existence Ordering

Entities are linked by explicit identifier fields rather than nested URL paths; a record's certifications, amendments, copies, and packets each reference it through a foreign-key field carried in the request body. For any request that names resources — whether by a path identifier or by an identifier in the body — the system validates their existence left to right and rejects at the first one that does not resolve, returning the not-found error specific to that entity type: `ERR_FACILITY_NOT_FOUND`, `ERR_CERTIFIER_NOT_FOUND`, `ERR_VITAL_EVENT_NOT_FOUND`, `ERR_CERTIFICATION_NOT_FOUND`, `ERR_AMENDMENT_NOT_FOUND`, `ERR_PATERNITY_NOT_FOUND`, `ERR_COPY_REQUEST_NOT_FOUND`, `ERR_APOSTILLE_NOT_FOUND`, `ERR_PACKET_NOT_FOUND`, or `ERR_REPORT_NOT_FOUND`, each with HTTP 404.

### 2.8. Fees, Cents, and Rounding

All monetary amounts are held as integer numbers of cents; the fields `delayed_fee_cents`, `fee_total_cents`, `fees_collected_cents`, `total_fees_collected_cents`, and `state_remittance_cents` are all integer cents. Most fee arithmetic is exact in cents and needs no rounding. Two places do require rounding, and both use the round-half-up method to the nearest whole cent: the halving of a certified copy fee for an indigent requester, and the per-transaction computation of the state's remittance share. Where rounding applies, it is applied at the exact step described in §3 — never earlier and never later — because rounding a running sum instead of each transaction yields a different, incorrect total.

### 2.9. Request Validation Order

When several checks could reject a request, they are evaluated in a fixed priority so that the returned error is deterministic. The order is:

1. Authentication — the headers are present and `X-User-Role` is a declared role, else `ERR_UNAUTHENTICATED` (401).
2. Authorization — the role is permitted to call the endpoint, else `ERR_UNAUTHORIZED` (403).
3. Ownership — for the two entity-backed actions (filing a vital event and signing a certification), the acting user owns the target, else `ERR_NOT_OWNER` (403).
4. Existence — every referenced resource resolves, left to right, else the appropriate `ERR_*_NOT_FOUND` (404).
5. Request shape — all required fields are present with valid types and enum values, else `ERR_INVALID_REQUEST` (400).
6. Body constraints — count fields are within range (`ERR_INVALID_COPY_COUNT`, 422) and amendment target consistency holds (`ERR_AMENDMENT_TARGET_REQUIRED`, 422), as described in §3.
7. State — the target is in a state from which the requested transition is defined, else `ERR_INVALID_STATE` (409).
8. Domain preconditions — the business, temporal, safety, and eligibility rules described in §3, each with its own error.
9. Optimistic concurrency — the `expected_vital_event_version` check (`ERR_STALE_EVENT_VERSION`, 412), evaluated last on the two operations that carry it.

Within an individual endpoint the domain preconditions themselves are ordered; those orderings are spelled out alongside the relevant workflow in §3. For example, when a copy is issued, the system checks that the copy is verified before it checks that the underlying record is registered, then eligibility, and only then the version.

## 3. Business Logic & Workflows

### 3.1. Registering a Vital Event

Records originate at filing facilities, which a `StateRegistrar` registers into the system with a `name`, a `facility_type` (one of `HOSPITAL`, `FUNERAL_HOME`, or `BIRTHING_CENTER`), the `jurisdiction_code` the facility files under, its `npi` national provider identifier, and an `active` flag defaulting to true that governs whether it may currently file.

The central record is the **vital event**. A `FacilityFiler` drafts a new electronic death or birth record by supplying its `event_type` (one of `BIRTH`, `DEATH`, or `FETAL_DEATH`), the `event_date` on which the event occurred, the subject's `subject_last_name` and `subject_first_name`, the recorded `sex` (one of `MALE`, `FEMALE`, or `UNDETERMINED`), the registration `jurisdiction_code`, the `facility_id` of the filing facility, and the free-text `place_of_event`. The filer may also set `foreign_born` to indicate the event occurred outside the state's territory; it defaults to false. A newly drafted record begins in `DRAFT` status. At creation the system pins `certification_required` to true exactly when `event_type` is `DEATH` or `FETAL_DEATH`, and false for a `BIRTH`; a death or fetal-death record cannot be registered until a certified cause of death exists.

Filing advances the record from `DRAFT` to `FILED`. Only the owning facility may file — the acting filer's identity must equal the record's `facility_id`. Filing stamps `filed_at` with the current clock instant and pins three derived values. First, `days_late` is the number of whole days between `event_date` and `filed_at`: the difference of the two instants in seconds, divided by 86,400, rounded down to a whole number. Second, the record's `registration_type` is classified. Each `event_type` has a statutory filing window — 10 days for `BIRTH`, 5 days for `DEATH`, and 5 days for `FETAL_DEATH`. If `foreign_born` is true, the type is `FOREIGN` regardless of elapsed days. Otherwise, if `days_late` is greater than the statutory window for the event type, the type is `DELAYED`; if `days_late` is less than or equal to the window, the type is `TIMELY`. Third, the system pins `delayed_fee_cents`: a `TIMELY` record carries 0, while a `DELAYED` or `FOREIGN` record carries a base surcharge of 2000 cents plus 100 cents for every full day of overage, where overage is `days_late` minus the statutory window but never less than zero, and the per-day portion is capped so that the total never exceeds the base plus 5000 cents. In other words the fee equals 2000 plus the smaller of 5000 and 100 times the overage.

A `StateRegistrar` registers a filed record, advancing it from `FILED` to `REGISTERED`. Registration is refused unless the record is in `FILED`. Two domain preconditions then apply. If `certification_required` is true, the record's `MedicalCertification` must be in `CERTIFIED` status, otherwise the request is rejected with `ERR_CERTIFICATION_REQUIRED`. If `registration_type` is `DELAYED` or `FOREIGN`, an accepted delayed-registration packet must exist for the record, otherwise the request is rejected with `ERR_DELAYED_REGISTRATION_REQUIRED`; certification is checked before the packet requirement. On success, registration stamps `registered_at` with the current clock instant and mints the `state_file_number`. The state file number has the form `{year}-{event_type}-{seq}`, where the year is the calendar year of `registered_at`, and `seq` is a six-digit, zero-padded sequence equal to one plus the count of prior `REGISTERED` or `AMENDED` events sharing the same `jurisdiction_code` and `event_type`, those prior events ordered by `registered_at` ascending and then by `created_at` ascending. Registration then sets `status` to `REGISTERED`, increments the filing facility's `registered_count` by one, and increments the event's `version` by one. When `certification_required` is true, registration also drives the linked certification from `CERTIFIED` to `LOCKED`, and that lock in turn increments the signing certifier's `locked_certification_count` by one — a three-link cascade from event registration to certification lock to certifier counter, all within the single request.

Not every filed record is accepted. A `StateRegistrar` may return a filed record to the facility for correction, moving it from `FILED` to `RETURNED`. A returned record is reopened for refiling: when the owning facility refiles a `RETURNED` record, the record first transitions from `RETURNED` back to `DRAFT` and is then filed again, recomputing `filed_at`, `days_late`, `registration_type`, and `delayed_fee_cents` exactly as on an initial filing.

Finally, a `StateRegistrar` may void a record that is `REGISTERED` or `AMENDED`, driving it to the terminal `VOIDED` state and reversing everything the registration and copy activity accumulated. Voiding sets `status` to `VOIDED`, decrements the facility's `registered_count` by one to compensate the earlier registration, and for every certified-copy request of the record whose `status` is `ISSUED`, reverses that copy by decrementing the event's `copies_issued_count` by one and decrementing `fees_collected_cents` by that copy's `fee_total_cents`. The event's `version` is incremented by one.

### 3.2. Medical Certification of Cause of Death

Before a death or fetal-death record can be registered, its cause of death must be certified. Certifiers are registered in the system with a `name`, a `certifier_type` (one of `PHYSICIAN`, `MEDICAL_EXAMINER`, or `CORONER`), a `license_number`, the `jurisdiction_code` in which they are authorized, and an `active` flag that defaults to true.

A `MedicalCertifier` opens a certification for a death or fetal-death event by supplying the `vital_event_id` of the event being certified, the `certifier_id` of the signing certifier, the `cause_of_death` narrative, and the `manner_of_death` classification (one of `NATURAL`, `ACCIDENT`, `SUICIDE`, `HOMICIDE`, `PENDING_INVESTIGATION`, or `UNDETERMINED`). A certification may be opened only for an event whose `event_type` is `DEATH` or `FETAL_DEATH`; opening one against a birth is rejected with `ERR_NOT_DEATH_EVENT`. At most one certification may exist per vital event; a second create for an event that already has one is rejected with `ERR_DUPLICATE_CERTIFICATION`. A new certification begins in `PENDING` status.

Signing advances the certification from `PENDING` to `CERTIFIED` and stamps `certified_at` with the current clock instant. Only the owning certifier may sign — the acting user's identity must equal the certification's `certifier_id`. A certification reaches `LOCKED` not by direct action but through the registration cascade described in §3.1: when the linked event is registered, its certification moves from `CERTIFIED` to `LOCKED` and the certifier's `locked_certification_count` rises by one. A locked certification is subsequently mutable only through the medical-amendment cascade described in §3.4, which moves it to `AMENDED`.

### 3.3. Delayed and Foreign Registration Proceedings

A record classified as `DELAYED` or `FOREIGN` at filing cannot be registered on documentary strength alone; it requires an accepted evidence packet backed by a registrar hearing. A `FacilityFiler` or a `StateRegistrar` submits a **delayed-registration packet** referencing the supporting record's `vital_event_id`, with a `packet_type` (`DELAYED` for late in-state events or `FOREIGN` for events that occurred outside the state), a `documentary_evidence_count` of attached evidence items that must be at least one — a value below one is rejected with `ERR_INVALID_COPY_COUNT` — and a reserved hearing slot given by `hearing_start`, `hearing_end`, and the `hearing_jurisdiction_code` whose calendar the slot is booked on. The `hearing_end` must be strictly after `hearing_start`. A new packet begins in `SUBMITTED` status.

A `StateRegistrar` accepts a submitted packet, advancing it from `SUBMITTED` to `ACCEPTED` and stamping `accepted_at`. Acceptance enforces a hearing-calendar conflict rule: within the same `hearing_jurisdiction_code`, the packet's reserved interval must not collide with the interval of any other packet whose `status` is `SUBMITTED` or `ACCEPTED`, where a collision is judged inclusively and with a 15-minute buffer. Two intervals collide when, after extending each reserved interval by 15 minutes at both ends, they share any instant, touching endpoints included; concretely, a conflict exists whenever the new packet's `hearing_start` is no later than the other packet's `hearing_end` plus 15 minutes and the other packet's `hearing_start` is no later than the new packet's `hearing_end` plus 15 minutes. A conflict is rejected with `ERR_HEARING_SLOT_CONFLICT`. A registrar may instead return a submitted packet for more evidence, moving it from `SUBMITTED` to `RETURNED`; a returned packet is reopened to `SUBMITTED` for another review cycle.

### 3.4. Amendments and Corrections

After a record is registered, a `StateRegistrar` may correct it through an **amendment**. An amendment is opened in `DRAFT` status with the `vital_event_id` of the record being corrected, an `amendment_type` of `DEMOGRAPHIC` or `MEDICAL`, the `field_name` to correct, the `new_value` to write on approval, and a `reason` justifying the change. A `MEDICAL` amendment corrects the cause-of-death certification and must supply the `target_certification_id` of the certification to amend; a `DEMOGRAPHIC` amendment corrects a record field and must omit it. Supplying a target on a demographic amendment, or omitting it on a medical one, is rejected with `ERR_AMENDMENT_TARGET_REQUIRED`.

Submission moves an amendment from `DRAFT` to `SUBMITTED`, and a rejected amendment may be resubmitted, moving from `REJECTED` back to `SUBMITTED`. Either way, the target record must be `REGISTERED` or `AMENDED`, otherwise submission is rejected with `ERR_EVENT_NOT_REGISTERED`. Submission pins `evidence_required`, which is true exactly when the current clock instant is later than the record's `registered_at` plus 365 days — corrections filed more than one year after registration require documentary evidence. A registrar may reject a submitted amendment, moving it from `SUBMITTED` to `REJECTED`.

Approval is the consequential act and drives the record itself. An amendment may be approved only from `SUBMITTED`, only while the target record is `REGISTERED` or `AMENDED` (else `ERR_EVENT_NOT_REGISTERED`), and only when the request's `expected_vital_event_version` matches the record's current `version` (else `ERR_STALE_EVENT_VERSION`, HTTP 412, as in §2.6). On success the amendment moves to the terminal `APPROVED` state and cascades into the record along one of two paths. A `DEMOGRAPHIC` approval writes the corrected value onto the record's named field — the field identified by `field_name` takes on `new_value` — increments the record's `amendment_count` by one, sets the record's `status` to `AMENDED`, and increments its `version` by one. A `MEDICAL` approval instead drives the target certification: the certification moves from `LOCKED` to `AMENDED` (or remains in `AMENDED` for a further medical correction), its `cause_of_death` takes on `new_value`, and its own `amendment_count` increases by one; that certification amendment in turn sets the parent record's `cause_of_death_amended` flag to true, increments the record's `amendment_count` by one, sets its `status` to `AMENDED`, and increments its `version` by one. Both cascade paths therefore advance the record's `version`, which is exactly why a second amendment approved against a stale observed version is caught by the concurrency check.

### 3.5. Acknowledgment of Paternity

For a registered birth record, paternity may be established through an **acknowledgment**. A `StateRegistrar` or an `Applicant` opens one in `DRAFT` status referencing the birth record's `vital_event_id` and supplying the acknowledging `father_last_name`, `father_first_name`, and a `mother_consent` flag; the creating actor's `X-User-ID` is recorded on the acknowledgment as `filed_by_user_id` for audit only.

A `StateRegistrar` then acknowledges it, moving it from `DRAFT` to `ACKNOWLEDGED`. Acknowledgment requires that the referenced event's `event_type` be `BIRTH` (else `ERR_NOT_BIRTH_EVENT`), that the event be `REGISTERED` or `AMENDED` (else `ERR_EVENT_NOT_REGISTERED`), and that `mother_consent` be true. It stamps `acknowledged_at` with the current clock instant, sets `rescission_deadline` to that instant plus 60 days, and cascades onto the birth record: the record's `father_last_name` and `father_first_name` take the acknowledged names, `paternity_established` is set to true, and the record's `version` increments by one.

An acknowledged paternity has a limited window to be undone. A `StateRegistrar` or an `Applicant` may rescind it, moving it from `ACKNOWLEDGED` to the terminal `RESCINDED` state, but only while the current clock instant is at or before `rescission_deadline`; a later attempt is rejected with `ERR_RESCISSION_WINDOW_CLOSED`. Rescission cascades onto the record, clearing `father_last_name` and `father_first_name` back to null, setting `paternity_established` to false, and incrementing the record's `version` by one. Conversely, a `StateRegistrar` may finalize an acknowledgment, moving it from `ACKNOWLEDGED` to the terminal `FINALIZED` state, but only once the window has closed — that is, only when the current clock instant is strictly after `rescission_deadline`; an attempt while the window is still open is rejected with `ERR_RESCISSION_WINDOW_OPEN`. Finalization carries no cascade.

### 3.6. Certified Copies, Eligibility, and Fees

Members of the public obtain copies of a record through a **certified-copy request**. An `Applicant` or a `StateRegistrar` creates one referencing the record's `vital_event_id` and supplying the `requester_name`, the `requester_relationship` to the record subject (one of `SELF`, `PARENT`, `CHILD`, `SPOUSE`, `SIBLING`, `LEGAL_GUARDIAN`, `LEGAL_REPRESENTATIVE`, `OTHER`, or `GENEALOGIST`), an optional `requester_category` fee class defaulting to `STANDARD` (otherwise `VETERAN` or `INDIGENT`), the `id_document_type` presented for identity (`DRIVERS_LICENSE`, `PASSPORT`, `STATE_ID`, or `MILITARY_ID`), a `copy_count` that must be at least one — a value below one is rejected with `ERR_INVALID_COPY_COUNT` — and an optional `expedite` flag defaulting to false. A new request begins in `SUBMITTED` status.

Processing proceeds in two registrar steps. Verifying identity moves the request from `SUBMITTED` to `ID_VERIFIED` and sets `id_verified` to true. Issuing the copies moves it from `ID_VERIFIED` to the terminal `ISSUED` state. Issuance enforces its preconditions in order: the request must already be `ID_VERIFIED` (an attempt while still `SUBMITTED` is rejected with `ERR_ID_NOT_VERIFIED`); the referenced record must be `REGISTERED` or `AMENDED` (else `ERR_EVENT_NOT_REGISTERED`); the eligibility rule below must resolve to a copy class; and finally `expected_vital_event_version` must match the record's current `version` (else `ERR_STALE_EVENT_VERSION`, HTTP 412). A registrar may instead deny a request that is `SUBMITTED` or `ID_VERIFIED`, moving it to the terminal `DENIED` state.

Eligibility fixes the request's `copy_class` from the record's age. The age in years is the number of whole years between the record's `event_date` and the current clock instant — their difference divided by 365 days, rounded down. Each `event_type` has a public-record threshold: 75 years for `BIRTH`, 25 years for `DEATH`, and 25 years for `FETAL_DEATH`. When the age is at least the threshold the record is public: `copy_class` is `INFORMATIONAL` and any requester qualifies regardless of relationship. When the age is below the threshold the record is confidential: `copy_class` is `CERTIFIED` only if `requester_relationship` is one of `SELF`, `PARENT`, `CHILD`, `SPOUSE`, `SIBLING`, `LEGAL_GUARDIAN`, or `LEGAL_REPRESENTATIVE`; a `requester_relationship` of `OTHER` or `GENEALOGIST` against a confidential record is rejected with `ERR_NOT_ELIGIBLE` (HTTP 403).

Issuance then prices the copies into `fee_total_cents`, evaluating in a fixed order — certified base first, then the expedite surcharge, then the category adjustment. For a `CERTIFIED` copy class, the base is a 1500-cent search fee plus 800 cents for each additional copy beyond the first, that is 800 cents times `copy_count` minus one; if `expedite` is true a 1900-cent surcharge is added to form the gross amount, and otherwise the gross equals the base. The category then adjusts the gross: a `VETERAN` requester pays 0, an `INDIGENT` requester pays the gross halved and rounded half up to a whole cent, and a `STANDARD` requester pays the full gross. For an `INFORMATIONAL` copy class, the fee is a flat 1000 cents per copy — 1000 cents times `copy_count` — plus the 1900-cent expedite surcharge when `expedite` is true; informational copies carry no search fee and no category waiver, so veterans and indigent requesters pay the same as standard requesters. On issuance the system stamps `issued_at`, sets `status` to `ISSUED`, increments the record's `copies_issued_count` by one, adds `fee_total_cents` to the record's `fees_collected_cents`, and increments the record's `version` by one.

### 3.7. International Authentication of Copies

An issued copy destined for use abroad can be authenticated through an **apostille request**. An `Applicant` or a `StateRegistrar` creates one referencing the `certified_copy_request_id` of the issued copy, the `destination_country` where the copy will be used, and an `apostille_type` of `APOSTILLE` for Hague-convention countries or `EXEMPLIFIED` for the chain authentication used by non-convention countries. A new request begins in `SUBMITTED` status.

A `StateRegistrar` authenticates a submitted request, advancing it from `SUBMITTED` to the terminal `AUTHENTICATED` state and stamping `authenticated_at`, but only when the referenced copy request is in `ISSUED` status; otherwise the request is rejected with `ERR_COPY_NOT_ISSUED`. A registrar may instead reject a submitted request, moving it from `SUBMITTED` to the terminal `REJECTED` state.

### 3.8. Statistical Reporting and State Remittance

Periodically a `StateRegistrar` compiles a **statistics report** for a jurisdiction over a window, supplying the `jurisdiction_code`, an inclusive `period_start`, and an exclusive `period_end`. A new report's window must not overlap an existing report in the same `jurisdiction_code`; adjacency is permitted, so a new window may begin exactly at the instant a prior window ended, but any true overlap is rejected with `ERR_REPORT_PERIOD_OVERLAP`.

Report creation computes its counts over the events belonging to the report's jurisdiction whose `status` is `REGISTERED` or `AMENDED` and whose `event_date` falls in the half-open window from `period_start` up to but not including `period_end`. Within that pool, `birth_count` is the number of `BIRTH` events, `death_count` the number of `DEATH` events, and `fetal_death_count` the number of `FETAL_DEATH` events.

Report creation also settles fee accounting. The relevant copies are the certified-copy requests whose `status` is `ISSUED`, whose record belongs to the report's jurisdiction, and whose `issued_at` falls in the same half-open window. The report's `total_fees_collected_cents` is the plain sum of `fee_total_cents` across those copies. The report's `state_remittance_cents` is the state's 45-percent share, computed per transaction and then summed: for each qualifying copy the system takes 45 percent of that copy's `fee_total_cents` and rounds it half up to a whole cent, and only then adds those rounded per-copy shares together. This ordering is significant — rounding the total after summing raw shares would produce a different, incorrect figure — so the rounding is always applied to each transaction before summation.

## 4. Endpoint Definitions

Operations that create a new stand-alone resource return `201 Created`. Operations that drive a state transition or otherwise modify an existing resource return `200 OK`. Every request and response is wrapped in the envelope of §2.2; the request bodies, preconditions, side effects, and cascades for each operation are described in the §3 narratives above.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/facilities` | Register a filing facility | StateRegistrar |
| GET | `/facilities/{id}` | Fetch a facility | StateRegistrar, FacilityFiler, MedicalCertifier, Applicant |
| POST | `/certifiers` | Register a medical certifier | StateRegistrar |
| GET | `/certifiers/{id}` | Fetch a certifier | StateRegistrar, MedicalCertifier, FacilityFiler |
| POST | `/vital-events` | Draft a new vital event record | FacilityFiler |
| GET | `/vital-events/{id}` | Fetch a vital event | StateRegistrar, FacilityFiler, MedicalCertifier, Applicant |
| GET | `/vital-events` | List vital events | StateRegistrar, FacilityFiler |
| POST | `/vital-events/{id}/file` | File a drafted or returned record | FacilityFiler |
| POST | `/vital-events/{id}/register` | Register a filed record | StateRegistrar |
| POST | `/vital-events/{id}/return` | Return a filed record to the facility | StateRegistrar |
| POST | `/vital-events/{id}/void` | Void a registered record | StateRegistrar |
| POST | `/certifications` | Open a cause-of-death certification | MedicalCertifier |
| GET | `/certifications/{id}` | Fetch a certification | StateRegistrar, MedicalCertifier, FacilityFiler |
| GET | `/certifications` | List certifications | StateRegistrar, MedicalCertifier |
| POST | `/certifications/{id}/certify` | Sign a certification | MedicalCertifier |
| POST | `/amendments` | Open a correction | StateRegistrar |
| GET | `/amendments/{id}` | Fetch an amendment | StateRegistrar, Applicant |
| GET | `/amendments` | List amendments | StateRegistrar |
| POST | `/amendments/{id}/submit` | Submit or resubmit a correction | StateRegistrar |
| POST | `/amendments/{id}/approve` | Approve a correction | StateRegistrar |
| POST | `/amendments/{id}/reject` | Reject a correction | StateRegistrar |
| POST | `/paternity-acknowledgments` | Open an acknowledgment of paternity | StateRegistrar, Applicant |
| GET | `/paternity-acknowledgments/{id}` | Fetch a paternity acknowledgment | StateRegistrar, Applicant |
| GET | `/paternity-acknowledgments` | List paternity acknowledgments | StateRegistrar |
| POST | `/paternity-acknowledgments/{id}/acknowledge` | Acknowledge paternity | StateRegistrar |
| POST | `/paternity-acknowledgments/{id}/rescind` | Rescind within the window | StateRegistrar, Applicant |
| POST | `/paternity-acknowledgments/{id}/finalize` | Finalize after the window closes | StateRegistrar |
| POST | `/certified-copy-requests` | Request certified copies | Applicant, StateRegistrar |
| GET | `/certified-copy-requests/{id}` | Fetch a copy request | StateRegistrar, Applicant |
| GET | `/certified-copy-requests` | List copy requests | StateRegistrar, Applicant |
| POST | `/certified-copy-requests/{id}/verify-id` | Verify presented identity | StateRegistrar |
| POST | `/certified-copy-requests/{id}/issue` | Issue the copies | StateRegistrar |
| POST | `/certified-copy-requests/{id}/deny` | Deny a copy request | StateRegistrar |
| POST | `/apostille-requests` | Request authentication of an issued copy | Applicant, StateRegistrar |
| GET | `/apostille-requests/{id}` | Fetch an apostille request | StateRegistrar, Applicant |
| GET | `/apostille-requests` | List apostille requests | StateRegistrar |
| POST | `/apostille-requests/{id}/authenticate` | Authenticate a submitted request | StateRegistrar |
| POST | `/apostille-requests/{id}/reject` | Reject a submitted request | StateRegistrar |
| POST | `/delayed-registration-packets` | Submit a delayed/foreign evidence packet | FacilityFiler, StateRegistrar |
| GET | `/delayed-registration-packets/{id}` | Fetch a packet | StateRegistrar, FacilityFiler |
| GET | `/delayed-registration-packets` | List packets | StateRegistrar |
| POST | `/delayed-registration-packets/{id}/accept` | Accept a packet or reopen a returned one | StateRegistrar |
| POST | `/delayed-registration-packets/{id}/return` | Return a packet for more evidence | StateRegistrar |
| POST | `/statistics-reports` | Generate a jurisdiction statistics report | StateRegistrar |
| GET | `/statistics-reports/{id}` | Fetch a statistics report | StateRegistrar |
| GET | `/statistics-reports` | List statistics reports | StateRegistrar |
| POST | `/_clock/set_current_utc` | Set the logical clock to a fixed instant | StateRegistrar |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_NOT_OWNER` | 403 |
| `ERR_FACILITY_NOT_FOUND` | 404 |
| `ERR_CERTIFIER_NOT_FOUND` | 404 |
| `ERR_VITAL_EVENT_NOT_FOUND` | 404 |
| `ERR_CERTIFICATION_NOT_FOUND` | 404 |
| `ERR_AMENDMENT_NOT_FOUND` | 404 |
| `ERR_PATERNITY_NOT_FOUND` | 404 |
| `ERR_COPY_REQUEST_NOT_FOUND` | 404 |
| `ERR_APOSTILLE_NOT_FOUND` | 404 |
| `ERR_PACKET_NOT_FOUND` | 404 |
| `ERR_REPORT_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_INVALID_COPY_COUNT` | 422 |
| `ERR_AMENDMENT_TARGET_REQUIRED` | 422 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_NOT_DEATH_EVENT` | 409 |
| `ERR_NOT_BIRTH_EVENT` | 409 |
| `ERR_DUPLICATE_CERTIFICATION` | 409 |
| `ERR_ID_NOT_VERIFIED` | 409 |
| `ERR_EVENT_NOT_REGISTERED` | 409 |
| `ERR_COPY_NOT_ISSUED` | 409 |
| `ERR_CERTIFICATION_REQUIRED` | 409 |
| `ERR_DELAYED_REGISTRATION_REQUIRED` | 409 |
| `ERR_RESCISSION_WINDOW_CLOSED` | 409 |
| `ERR_RESCISSION_WINDOW_OPEN` | 409 |
| `ERR_HEARING_SLOT_CONFLICT` | 409 |
| `ERR_REPORT_PERIOD_OVERLAP` | 409 |
| `ERR_NOT_ELIGIBLE` | 403 |
| `ERR_STALE_EVENT_VERSION` | 412 |
