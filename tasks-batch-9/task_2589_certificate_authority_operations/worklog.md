# Worklog — task_2589_certificate_authority_operations

## Step 1: Create task directory — 2026-09-03T15:15:05.964Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2589_certificate_authority_operations` and `.../workspace` (pre-assigned path; no index auto-allocation performed).

## Step 2: Generate scaffold — 2026-09-03T17:20:37.628Z

All three artifacts are complete and the linter is clean.

```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           tasks/task_2589_certificate_authority_operations/SCAFFOLD.yaml
  Difficulty design:  tasks/task_2589_certificate_authority_operations/SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      tasks/task_2589_certificate_authority_operations/SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    64
  §1.1 entities declared:     14
  §1.8 instances scanned:     21
  §1.9 instances scanned:     74
  Calls scanned (§1.8+§1.9):  1207

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

## Files

- `SCAFFOLD.yaml` — 3,424 lines
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 2,172 lines
- `SCAFFOLD_CORNER_DESIGN.yaml` — 5,592 lines

All three `yaml.safe_load` cleanly. `SCAFFOLD.yaml` carries neither design key; each design file has exactly one top-level key.

## SCAFFOLD.yaml (§1.0–§1.7)

`api_prefix: /ca`, `difficulty_level: expert_plus`, `consistency_model: immediate`.

14 entities (CertificateProfile, Subscriber, DomainAuthorization, OrganizationVetting, VettingCheck, HsmPartition, KeyCeremony, CeremonyWitness, CertificateRequest, Certificate, CtLogSubmission, RevocationRequest, CrlPublication, MisissuanceIncident, plus RootProgramAudit / AuditFinding / RootProgramCommunication in the audit cluster — 14 with `common_fields` entities and immutable ledgers counted as declared) · 13 state machines · 2 `concurrency_rules` · 12 calculations · 90 validations (strictly ascending priority ladder) · 64 endpoints · 90 errors (all unique) · 6 roles (POLICY_ADMIN, VALIDATION_OFFICER, VETTING_APPROVER, ISSUANCE_OPERATOR, REVOCATION_OFFICER, COMPLIANCE_AUDITOR).

## §1.8 — 9 rule ids / 21 instances

dual_variant_calc 2 · combinatorial_formula 2 · non_linear_state_machine 2 · transitive_cascade 2 · priority_pair_validation_conflict 3 · boundary_precision_check 3 · cross_entity_state_dependency 2 · resource_temporal_overlap 2 · compensating_invariant 3.

## §1.9 — 9 sections / 97 instances (74 recipes + 23 `excluded_because` stubs)

entities 15 · state_machines 16 · calculations 16 · validations 12 · endpoints 8 · errors 13 · rbac 7 · cross_cutting_complexity_layers 8 · consistency_model 2.

## Adjudications

- **Error triggerability audit**: all 90 catalog ids are referenced by at least one §1.8/§1.9 instance (verified programmatically, zero uncovered). The two OCC ids land in `cross_cutting_complexity_layers`, the three segregation-of-duties ids in `rbac`, and 13 dedicated errors-section instances mop up the rest.
- **`claim_type` for the errors section**: the claim-extraction guide's Table 6 has no rows, so I used `violation_to_error` per SKILL.md's own errors-section stub example.
- **Three SCAFFOLD.yaml defects self-found and fixed while writing recipes**: (1) the vetting `checks` endpoint used an undeclared body field name and undeclared `dimension`/`outcome` enums — description now declares `REGISTRY|CALLBACK|AUTHORITY` and `PASSED|FAILED`, and three `written_by` strings were realigned; (2) the audit `findings` endpoint's `severity` enum (`MINOR|MAJOR|CRITICAL`) was undeclared; (3) `ERR_CERTIFICATE_ALREADY_EXPIRED` was unreachable at priority 112 behind the lifecycle check — moved to priority 29 with a note explaining that clock sweep 2 flips PREISSUANCE→EXPIRED, and `ERR_CERTIFICATE_NOT_PREISSUANCE` stays reachable via an already-ISSUED certificate.
- **Cascade/threshold semantics pinned**: subscriber suspension is a reversible counter (trips at `revocation_pending_count >= 2`, resets on deny *or* execute); profile posture flips `NOMINAL→CRL_OVERDUE` at `pending_crl_entry_count >= crl_trigger_threshold` and blocks `READY_TO_ISSUE` requests with `blocked_reason PROFILE_STATUS_SERVICE_OVERDUE`, draining fully on one publication; mass revocation deliberately bypasses `REVOCATION_PENDING` and leaves the subscriber counter untouched.
- **Duplication policy**: every corner claim already fully exercised by a §1.8 instance is a stub citing that instance verbatim (23 of them, all targets verified to exist in the difficulty file, none carrying a `test_recipe`), notably both cascade layers and both dual-variant layers.
- `required_sct_count: 0` is used in concurrency/threshold recipes so version arithmetic stays exact, and `required_sct_count: 2` in the consistency recipe so the denormalised `sct_count` (with duplicate/rejected appends that must not move it) is observable.

## Step 3: Copy shared files — 2026-09-03T17:20:37.628Z

Copied `./INSTRUCTION.md` → `tasks/task_2589_certificate_authority_operations/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-03T17:37:34.000Z

PRD generated at `workspace/PRD.md`.

**Size:** 497 lines. Built with 8 chunked `cat >>` appends (no single giant Write); file ends at a real boundary — the last row of the §5 error table plus a trailing newline, no audit footer.

**Section list**
- `# Certificate Authority Operations API — Product Requirements Document`
- §1 Introduction
- §2 Global Specifications & System-Wide Principles — 2.1 Operator Identity and RBAC; 2.2 API Response Structure (byte-identical copy of the skill's fixed section, incl. both `####` sub-blocks); 2.3 Pagination, Filtering and List Ordering; 2.4 Resource Identity, Timestamps and the Version Counter; 2.5 Optimistic Concurrency on Certificates and Profiles; 2.6 The Logical Clock and its Three Advancement Sweeps; 2.7 Segregation of Duties Across Three Duty Pairs; 2.8 Validation Precedence: One Global, Strictly Ordered Ladder; 2.9 Precision, Rounding and the Conserved Money Ledger; 2.10 The Revocation Conservation Invariant and Status-Service Posture; 2.11 Deterministic Ordering of Cascades and Batches
- §3 Business Logic & Workflows — 3.1 Certificate Profiles; 3.2 Subscribers: Accounts, Credit and Account Posture; 3.3 Organizational Vetting; 3.4 Domain Control Validation; 3.5 The Certificate Request Pipeline; 3.6 Signing Infrastructure: Partitions, Ceremony Windows and Attestation; 3.7 Issuance, Transparency Logging and Activation; 3.8 Revocation Processing and the Status Services; 3.9 Compliance Operations: Misissuance Incidents, Mass Revocation and Root Program Audits (**9 subsections**, inside the 5–9 band)
- §4 API Endpoint Definitions — 4-column table, **64 rows** (the scaffold has 64 endpoints, not 55)
- §5 Error Handling — 2-column table, **90 rows**

**Hard Contract results (verified programmatically, code fences stripped so backtick pairing is correct)**
- **Contract 1 Field-Name Coverage — PASS.** All 175 `entities[].fields[].name` values appear verbatim in backticks; all 78 distinct endpoint `input` identifiers (incl. optional ones, `expected_certificate_version`, `expected_profile_version`, `current_utc`, every filter query param) appear verbatim. Zero misses.
- **Contract 2 Rule Coverage — PASS.** All 90 error IDs appear in §1–§4 prose *before* the §5 table (none exists only in the table); every state value across all 13 state-machine dimensions appears; all 12 calculations are narrated with their constants (validity window, charge settlement incl. the six-step tiered pricing, both `subscriber_risk_score` variants, remediation penalty, revocation deadline, DCV selection, mass-revocation selection, CRL drain, SCT sufficiency, ceremony window occupation, CRL window coverage, disclosure deadline); both `concurrency_rules` in §2.5; all `ERR_VALUE_OUT_OF_RANGE` numeric ranges in §3.1/§3.5/§3.6; all cascade orderings and sibling-branch symmetry (QUALIFIED vs UNQUALIFIED).
- **Contract 3 §3 Path Purity — PASS.** Zero backticked tokens in §3 begin with `/`, are a bare HTTP method, or combine method+path. Every operation is framed as state transition or role + action verb; paths appear only in §1/§2 mount references and the §4 table.

**Coverage decisions**
1. **Role-name conflict resolved in favour of `roles[]`.** `state_machines[].transitions[].actor` uses legacy labels (`CaAdmin`, `ValidationSpecialist`, `IssuanceOfficer`, `ComplianceOfficer`, `Auditor`, `Subscriber`) that don't match any `roles[].name`. I treated `roles[].name` plus each endpoint's `roles:` list as authoritative and used only the six real roles throughout. Notably the scaffold's actor for revocation *execute* is `IssuanceOfficer` while the endpoint grants `REVOCATION_OFFICER`; the PRD says `REVOCATION_OFFICER`.
2. **Invented the incident→reason-code mapping (the one unavoidable invention).** The scaffold says mass revocation sets `revocation_reason_code` "per the incident category mapping" but never defines that mapping. I stated it explicitly: `KEY_COMPROMISE`→`KEY_COMPROMISE`, `DOMAIN_MISISSUANCE`→`PRIVILEGE_WITHDRAWN`, `ORG_MISISSUANCE`→`AFFILIATION_CHANGED`, `PROCEDURAL`→`UNSPECIFIED`. Without it an implementer has no determinate answer.
3. **`evidence_ref` conditional requirement mapped to an existing code.** The scaffold marks it "required when `reason_code` is `KEY_COMPROMISE`" but gives it no error ID; I routed it through the missing-required-field rule, `ERR_INVALID_REQUEST` (400), rather than minting a code.
4. **Issue-time authorization freshness** ("every consumed authorization still `VALIDATED` with `expires_at` after the clock") has no error ID in any `applies_to`; I named `ERR_DOMAIN_AUTHORIZATION_EXPIRED` as its refusal code at issuance so the behaviour is determinate.
5. **Audit period non-overlap** has no error ID. I stated the enforceable rule — no `SCHEDULED`/`FIELDWORK` audit may exist for the same `root_program`, i.e. `ERR_AUDIT_ALREADY_OPEN` — and mentioned non-overlap only as the intent that rule serves.
6. **Preconditions without codes stated but not code-ified:** the profile-activation tier precondition and the certificate-activation `revocation_status == NONE` precondition are described as requirements without inventing error IDs.
7. **§4 shorthand:** the intro paragraph defines "All roles" as all six role names (used for the read-only rows) so the table stays legible without dropping any role information.

**Orchestrator truncation check:** PASS — `wc -l` 497, 5 top-level sections present, tail ends on a complete error-table row (`| ERR_CREDIT_LIMIT_EXCEEDED | 402 |`), not mid-sentence.

## Step 6: Generate implementation — 2026-09-03T18:16:00.000Z

Implementation complete and verified end-to-end.

## Files written (`workspace/implementation/`)

| lines | file |
|---|---|
| 73 | `app.py` (global RLock request serialization, blueprint registration, 3 error handlers, `0.0.0.0:$PORT`) |
| 133 | `db.py` (in-memory `Store`, logical clock, id/serial/token counters, `iso`/`make_record`/`touch`/`public`/`sort_records`) |
| 111 | `errors.py` (all 90 error ids → exact PRD §5 HTTP statuses) |
| 76 | `response.py` (envelope, pagination in `meta`) |
| 51 | `middleware.py` (`X-User-ID`/`X-User-Role`, band-1 auth ordering) |
| 136 | `validation.py` (enum vocabularies + typed getters) |
| 28 | `filters.py` |
| 207 / 215 / 141 / 358 / 119 / 186 / 166 / 254 / 186 / 47 | `routes/{profiles,subscribers,authorizations,requests,certificates,partitions,revocations,incidents,audits,clock}.py` |
| 149 / 191 / 60 | `services/{calc,cascade,lookup}.py` |
| 8 | `start.sh` (guarded `pip install`, `exec python3 app.py`, chmod +x) |
| 1 | `requirements.txt` (`flask>=2.0.0`) |

**2887 Python lines across 22 modules.** `python3 -m py_compile` clean on all files; `__pycache__` removed. All **64 PRD §4 endpoints** registered (verified programmatically: no missing, no extra). Store is empty on boot — no seeding anywhere.

## Runtime verification (two fresh boots, killed by PID only; ports 18589/18590 confirmed free)

Two scripted smoke suites passed: full issuance chain (profile create/activate → subscriber → OV/EV vetting with SoD rejection → DCV authorization with failed-then-successful attempt → request submit/clear-validation → partition/ceremony with window-buffer conflict, 2 witnesses, attester-was-witness rejection, attest → issuance SoD rejection → issue → CT dedup → activate), revocation (evidence_ref gate, OCC 412, execute, posture flip to `CRL_OVERDUE`, CRL publication draining serial `1000001`, posture restore), clock (non-monotonic 422 + both expiry sweeps), all four auth bands, and the incident + audit flows (disclosure comm `within_deadline`, breach-escalation gate, 3-cert mass revoke → `REMEDIATED` with `PRIVILEGE_WITHDRAWN` reason and 6000c penalty, close → risk back to 0; audit already-open, 366-day period, no-findings 422, `QUALIFIED`, re-opine 409, `risk_score_audit_final` 25.0 for an open incident vs 12.5 for a closed one, notice comms, pagination clamp `limit=500→100`, `offset=-4→0`).

Charge math checked against a worked case: base 33333 × EV 2.5 = 83333 (ROUND_HALF_UP), −10% band = 75000, +25% expedited = **93750**. Validity floor checked: `not_after = min(clock+90d cap, auth.expires_at, attestation_expires_at)` → `2026-08-31T00:00:00.000Z`, `validity_days_final = 30`.

## PRD ambiguities resolved

1. **Issue-gate ordering conflict.** §3.7's narration puts `REQUEST_NOT_READY`/quarantine/SoD/ceremony gates *above* subscriber+profile state, while §2.8's self-declared global ladder (matching scaffold `priority` 31/32/33 → 41 → 45 → 64 → 70/71 → 74 → 100 → 120) puts the whole state band above SoD and says a wrong-state target is reported before a duty conflict. **Implemented §2.8's global ladder.**
2. **List ordering.** §2.3/§4 say ascending `created_at`; SCAFFOLD says "newest first". **PRD wins → ascending**, with insertion sequence as deterministic tie-break. Documented exceptions honored: CRL publications by `crl_number`, ceremonies by `window_start`, communications by `sent_at`.
3. **§4's description column is stale** in places (subscriber `PENDING_VETTING`, invalidate → `EXPIRED`, partition `AVAILABLE`, projections at request creation). Treated §4 as authoritative only for method/path/role/status; followed §3 prose + scaffold fields otherwise.
4. `org_vetting_reuse_days` treated as **optional, default 0** (so DV may omit it); the DV-must-be-0 / OV-EV 1..825 rule enforced as `ERR_VALUE_OUT_OF_RANGE`.
5. **String format/length violations** (name lengths, uppercase jurisdiction, `@` in email, domain shape) have no assigned error → reported as `ERR_INVALID_REQUEST` (400).
6. **Activate with `revocation_status != NONE`** has no declared error → `ERR_CERTIFICATE_NOT_PREISSUANCE` (409).
7. `remaining_scope_count` **initialised to 0** at incident creation (§3.9 + scaffold side-effects, against the entity note "recomputed at creation").
8. **Version-bump multiplicity:** profile bumps once per certificate in a mass-revoke batch plus once more on posture flip; `risk_score_operational` recomputation bumps the subscriber only when the value changes; drained certificates get a bump on CRL publication.
9. `POST /_clock/set_current_utc` returns `data: {}` (scaffold says `output: null`) and requires `X-User-ID` as a non-GET.
10. `challenge_token` is deterministic (`dcv-challenge-%06d`) and returned at authorization creation; `api_request_timestamp` renders the logical clock.
11. Termination on mass revoke additionally requires the batch to have revoked ≥1 of the attributed subscriber's certificates (§3.2's stricter phrasing over §3.9's).

## Step 5: Generate unit tests — 2026-09-03T19:34:00.000Z

Suite complete and fully verified.

## Output paths (both directly under the task root, not under `workspace/`)
`test_helpers/` and `test_suite/`

**test_suite/** (13,798 lines total with helpers)

| file | lines | tests | source |
|---|---|---|---|
| conftest.py | 20 | – | re-exports fixtures; no `pytest_plugins` |
| test_01_validity_and_risk_dual_variants.py | 424 | 4 | queue A |
| test_02_charge_and_penalty_formulas.py | 344 | 4 | A |
| test_03_lifecycle_state_machines.py | 323 | 4 | A |
| test_04_cascades.py | 440 | 4 | A |
| test_05_error_precedence.py | 430 | 6 | A |
| test_06_boundaries.py | 495 | 6 | A |
| test_07_cross_entity_dependencies.py | 448 | 4 | A |
| test_08_temporal_overlap.py | 387 | 4 | A |
| test_09_conservation_invariants.py | 556 | 6 | A |
| test_10_entities.py | 832 | 15 | queue B |
| test_11_state_machines.py | 1114 | 17 | B |
| test_12_calculations.py | 536 | 7 | B |
| test_13_validations.py | 662 | 12 | B |
| test_14_endpoints.py | 540 | 8 | B |
| test_15_errors.py | 1476 | 24 | B |
| test_16_rbac.py | 798 | 14 | B |
| test_17_cross_cutting.py | 630 | 9 | B |
| test_18_consistency.py | 490 | 7 | B |

**test_helpers/**: `__init__.py` 157, `api_client.py` 443, `api_errors.py` 224, `assertions.py` 349, `constants.py` 320, `factories.py` 354, `fixtures.py` 623, `test_users.py` 126, `types.py` 257.

## Tests per queue
- Queue A (§1.8 difficulty): **42 tests** across 9 files — all 21 instances covered, exactly 2 tests each.
- Queue B (§1.9 corner): **113 tests** across 9 files — all 74 non-stub instances covered (≥1 each).
- **155 test functions**, 168 collected items (3 `parametrize` decorators expand 13 extra cases).

## Skipped instances
**Zero PRD-first skips.** Every non-stub instance in both indices passed the two-condition filter and was translated. The only untranslated instances are the 23 `excluded_because:` stubs in `SCAFFOLD_CORNER_DESIGN.yaml` (depth corners already owned by §1.8), which are never translated by contract: calculations 9, state_machines 4, cross_cutting_complexity_layers 4, endpoints 3, validations 2, rbac 1.

## Verification (whole suite, all 18 files together)
- `py_compile` clean on all 27 `.py` files; `pyflakes` reports only unused re-exported imports, no errors.
- `pytest --collect-only -q -p prd_bench_local_runner.pytest_plugin` → **168 tests collected, 0 errors**.
- Citations: **342 PRD quotes, 0 problems** — every quote is verbatim-greppable in `workspace/PRD.md` and its cited section matches an occurrence.
- Tags: **155 tests, 0 problems** — exactly one `Design:` line per test, every `<name>` resolves to a real instance; 95 distinct instances tagged (21 + 74); no stub tagged; no unknown tags; no instance split across files.
- No `scaffold`/`xfail`/`skipif`/`pytest.skip`/`pytest_plugins` anywhere; no mocking/monkeypatching.
- Task root holds only `SCAFFOLD*.yaml`, `test_helpers/`, `test_suite/`, `worklog.md`, `workspace/`; `__pycache__` removed.

## Notes worth relaying
- Fixed a latent helper bug in `test_helpers/assertions.py`: `assert_envelope_meta` read `response_type` from `meta`, but PRD 2.2 places it at the envelope top level (now reads top level with a `meta` fallback).
- Where a design recipe contradicted the PRD, tests follow the PRD: the `projected_not_after` off-by-30-minutes in `certificate_read_exposes_the_derived_method_set_and_final_validity`; recipes' invalid `jurisdiction_code: "US-DE"` (PRD 3.2 requires 2–6 uppercase, so `USDE`/`USNY`); the `sct_timestamp`-only-on-ACCEPTED claim (PRD 3.7 stamps every submission); the "§1.5 declares no PATCH/PUT/DELETE" claim, which is not a PRD statement; and the pervasive `org_vetting_reuse_days`-on-DV recipe bug, avoided by using the profile factory defaults.
- PRD internal inconsistency found: §4's endpoint table says a subscriber registers in `PENDING_VETTING` and that PATCH updates `technical_contact_email`, while §3.2 prose says registration lands in `ACTIVE` with amendable fields `credit_limit_cents`, `contact_email`, `callback_phone` (`technical_contact_email` is defined nowhere else). Tests follow the rule-bearing §3.2 prose.

## Step 7: Run tests and iterate — 2026-09-03T19:44:21.484Z

All 8 rounds are green. Final state:

```
results.1..8.json → total 168 | passed 168 | failed 0 | errors 0   (each round ~370s)
```

## Summary

**Iterations run:** 2 full 8-round parallel sweeps (both under `setsid nohup`, all 8 rounds run to completion, results at `workspace/implementation/results.{1..8}.json`, log at `workspace/sweep.log`). Iteration 1: 10 failures, identical in all 8 rounds (fully deterministic — no flakiness, no reaping signature). Iteration 2 after the fix batch: 168/168 in all 8 rounds.

Note on triage: `workspace/sweep.log` is written by 8 concurrent processes into one file, so its `FAILED` lines are interleaved/garbled and mis-attribute failures to the wrong nodeids (~19 apparent names vs. the real 10). Only the per-round `results.*.json` are trustworthy.

**Tests deleted:** none. Every failure traced either to a verbatim PRD rule the implementation broke, or to a test/setup step that contradicted PRD prose.

**Fixes applied to `test_suite/` (test bugs — each makes the test more faithful to PRD):**
- `test_suite/test_01_validity_and_risk_dual_variants.py` — `_opine_mozilla_audit`: `record_finding` expected 201; PRD §4 ("Endpoints that create a new resource return HTTP 201; endpoints that modify or transition an existing resource … return HTTP 200") annotates *every* creating POST with "Returns 201" and pointedly does **not** annotate `POST /ca/root-program-audits/{id}/findings`; a finding has no id/resource in the PRD and the analogous `/checks` row is explicitly "The response is 200 with the updated file". Now expects 200.
- `test_suite/test_01_…py` — `_two_attributed_incidents` returned the *creation* response, so `assert first["state"] == INCIDENT_CLOSED` asserted a stale `OPEN` snapshot. Now returns the close response (post-transition state) for both incidents.
- `test_suite/test_15_errors.py` — `TestAuditOpinionGates::test_c`: same 201→200 on `record_finding`.
- `test_suite/test_03_lifecycle_state_machines.py` — `TestCertificateParallelDimensions::test_b`: raised a `KEY_COMPROMISE` revocation with no `evidence_ref`; PRD §3.8 makes it conditionally mandatory (`ERR_INVALID_REQUEST`). Setup now supplies `evidence_ref`.
- `test_suite/test_09_conservation_invariants.py` — `TestSubscriberBalanceConservation::test_d`: same missing `evidence_ref` on the `KEY_COMPROMISE` leg.
- `test_suite/test_06_boundaries.py` — `TestSctCountAtTheThreshold::test_a`: garbled `_submit(...)` call passed `COMM_INCIDENT_DISCLOSURE` as `outcome` and `CT_OUTCOME_ACCEPTED` as `rejection_reason` (PRD §3.7 allows only `ACCEPTED`/`REJECTED`). Now passes `CT_OUTCOME_ACCEPTED` as the outcome.
- `test_suite/test_10_entities.py` — `TestMissingAndMalformedInput::test_a_vetting_file_cannot_be_opened_under_a_missing_subscriber`: called `client.list_vettings(headers)` (TypeError); PRD exposes vetting listing only as `GET /ca/subscribers/{id}/organization-vettings`. Now lists under the real subscriber created in the setup.
- `test_suite/test_12_calculations.py` — `TestMassRevocationScope`: called `mass-revoke` as `COMPLIANCE_AUDITOR`; PRD §4 authorizes `REVOCATION_OFFICER` (so `ERR_UNAUTHORIZED` was correct per §2.8 band 1). Now uses `REVOCATION_OFFICER`.

**Fixes applied to `test_helpers/`:**
- `test_helpers/fixtures.py` — `audit_with_findings`: same 201→200 expectation on `record_finding` (helper is currently unused by the suite, corrected for consistency).

**Fixes applied to `implementation/`:**
- `workspace/implementation/routes/profiles.py`, `create_profile` — duplicate-name check was case-sensitive; PRD §3.1: "a `name` … unique across all profiles after case-folding — a second profile whose name differs only in letter case is rejected with `ERR_PROFILE_NAME_DUPLICATE`". Now compares `casefold()`.
- `workspace/implementation/routes/requests.py`, `create_request` — the per-domain shape check (`check_domain_name`, which raises `ERR_INVALID_REQUEST` for a non-lowercase name) ran before the case-folded duplicate check, masking the rule PRD §3.5 explicitly maps to `ERR_INVALID_ARRAY_CONTENT` (422). Duplicate-after-case-folding is now evaluated first.

No endpoint, field, side effect or capability was added; storage remains in-memory dicts with no startup seeding.

**Orchestrator verification:** re-read all 8 `results.*.json` independently — every round reports `total 168 | passed 168 | failed 0 | errors 0`; `sweep.log` tail confirms `168/168 passed` and the final round finished 19:33:07Z (~378s per round).

## Step 8: Finalize PRD — 2026-09-03T19:50:00.000Z

Done. `PRD_FINALIZED.md` written with two sentence-level inserts; the file is intact (identical line count, error table complete at tail).

## Line counts
- `PRD.md`: 497 lines / 109,257 bytes
- `PRD_FINALIZED.md`: 497 lines / 109,959 bytes (+0.0% lines, +0.64% bytes — both edits are appended sentences inside existing long paragraphs)

## Changes
- **§3.5 (certificate request creation)** — insert — pinned that the `requested_domains` array-content rules (count bounds, duplicate-after-case-folding) are evaluated **before** the per-name shape rules, so a case-folded collision reports `ERR_INVALID_ARRAY_CONTENT` even when one spelling is not lowercase, and a surviving entry that fails the shape rules is `ERR_INVALID_REQUEST` — `implementation/routes/requests.py:37-47`, `implementation/validation.py:124-136`.
- **§3.9 (audit findings)** — insert — pinned that a finding is not a stored resource and that `POST /ca/root-program-audits/{id}/findings` answers 200 with the updated audit, not 201 — `implementation/routes/audits.py:84-101`.

## Step 7 items that needed no PRD edit
- All six `test_suite/` fixture/setup bugs (stale creation snapshot, missing `evidence_ref` on `KEY_COMPROMISE`, garbled `_submit` args, `list_vettings` TypeError, wrong role on `mass-revoke`) — PRD already determines each verbatim (§3.8 conditional `evidence_ref`, §3.7 CT outcomes, §4 vetting-list path, §4 `REVOCATION_OFFICER` on mass-revoke).
- `profiles.py` case-folded name duplicate — PRD §3.1 already states case-folded uniqueness verbatim; the fix moved impl **to** the PRD, so prose kept verbatim.
- The `test_helpers/fixtures.py` 201→200 change is the same subject as the §3.9 edit (no separate patch).

## Per-edit pre-edit search log

**Edit 1 — §3.5 array-content vs. name-shape ordering**
- (a) Subject: validation of `requested_domains` entries at request creation — which error id fires and in what order.
- (b) Enumerated/read: `routes/requests.py::create_request` (lines 27-50: `req_str`/`req_list`/`req_int` → `in_range(requested_validity_days)` → `one_of_range(csr_key_bits)` → count bounds → per-element string check → duplicate over `.lower()` → `check_domain_name` per entry → then `get_profile`/`get_subscriber`); `validation.py::check_domain_name` (all four shape rules route through `_bad` → `ERR_INVALID_REQUEST`); `validation.py::in_range`/`one_of_range`/`req_list`; the **other** `check_domain_name` callsite `routes/authorizations.py:29` (single `domain_name`, same helper, same `ERR_INVALID_REQUEST`); downstream consumers of `requested_domains` that do *not* re-validate (`clear_validation` lines 164-206, `issue_certificate` line 308); `routes/profiles.py::create_profile` as the parallel `ERR_INVALID_ARRAY_CONTENT` site (lines 39-59: enum-per-method and integer ranges precede the array count/distinct check).
- (c) Adjustment: scoped the sentence to `requested_domains` and phrased the ordering claim as array-content-before-*name shape* only, rather than "array content is checked first". A blanket claim would have contradicted `create_request`'s range checks (`requested_validity_days`, `csr_key_bits`) and `create_profile`'s enum/range checks, which both run *before* array content per §2.8 band 2. Also referenced §3.4's existing shape wording instead of restating a new rule, and said nothing about non-string entries (impl maps those to `ERR_INVALID_ARRAY_CONTENT`, which PRD leaves open — left under-determined rather than risking a false claim).

**Edit 2 — §3.9 finding response is 200 with the audit**
- (a) Subject: the persisted-ness of a finding and the status/body of `POST /ca/root-program-audits/{id}/findings`.
- (b) Enumerated/read: `routes/audits.py::record_finding` (returns `ok(public(audit))`, mutates `finding_count`/`critical_finding_count`/`state`, discards `severity`/`summary`); `grep -rn "finding" implementation/` outside `audits.py` → **zero** hits, so no findings store, no finding read/list endpoint, no cascade reads a finding row; `db.py:25-38` store inventory (no `findings` dict); `response.py::ok`/`created` (201 is `ok(..., 201)`); sibling endpoints for consistency — `create_audit` → 201, `opine_audit` → 200, `create_audit_communication` → 201 (a real immutable record); and `routes/incidents.py::close_incident` → 200 with the updated incident, which confirms the "transition returns the updated parent" pattern the second Step 7 test bug assumed.
- (c) Adjustment: added the justification clause ("not itself a stored, addressable resource … counter and state movement on the audit") so the 200 does not read as an exception to §4's create-returns-201 rule, and worded it as "rather than 201 with a finding record" to stay consistent with §2.4, which never lists a finding among the resource types carrying `id`/`created_at`. Did not assert anything about `summary`/`severity` retention, since nothing in the API can observe it.

## Step 9: Complete PRD — 2026-09-03T20:15:44.282Z

Pass C complete; verification run and clean. Executed as three sequential file-partitioned passes (A: core modules + services; B: profiles/subscribers/authorizations/requests/clock routes; C: certificates/partitions/revocations/incidents/audits routes).

## Result

`workspace/PRD_COMPLETED.md` written as a minimal in-place patch over `workspace/PRD_FINALIZED.md`.

- **PRD_FINALIZED.md**: 497 lines, 109,959 bytes
- **PRD_COMPLETED.md**: 497 lines, 122,790 bytes (**+12,831 chars**, line count unchanged — every patch is an in-paragraph insert or revision; no new sections, no new paragraphs)
- **diff**: 52 hunks, 64 changed lines (64 `<` / 64 `>`)
- **tail check**: ends at `| ERR_CREDIT_LIMIT_EXCEEDED | 402 |`, the last row of the §5 error table — a real section boundary
- **Counts**: 29 ambiguity-pins, 23 mismatch-revisions

## Changes

- §2.1 — insert — ambiguity — header trim/whitespace-is-empty, and the four-step order missing-user → missing-role → unknown-role → unauthorized; read endpoints do not require `X-User-ID` — `middleware.py:20-45`
- §2.3 — insert — ambiguity — `limit`/`offset` out-of-bounds are silently clamped, unparseable falls back to default, so no list ever errors on pagination — `response.py:14-40`
- §2.3 — insert — ambiguity — filter semantics: string filters compare raw, bool filters accept `true`/`false` only — `filters.py`
- §2.3 — insert — ambiguity — list ties on `created_at` break by insertion sequence — `db.py` (`sort_records`)
- §2.4 — insert — ambiguity — timestamps render exactly 3 fractional digits; `api_request_id` is `req_` + 20 hex — `db.py` (`iso`), `response.py`
- §2.4 — insert — ambiguity — `version`/`updated_at` move only on genuine mutation; two mutations in one call move `version` twice — `db.py` (`touch`)
- §2.6 — insert — ambiguity — clock endpoint answers 200 with an empty `data` object; the three sweeps run in a pinned order over insertion-ordered records — `routes/clock.py`
- §2.8 — insert — ambiguity — non-dict body and unparseable timestamps map to `ERR_INVALID_REQUEST`; absent body is treated as `{}` — `middleware.py` (`json_body`), `validation.py`
- §2.8 — revise — mismatch — band-5 ordering carve-out: revocation execution tests `ERR_REVOCATION_REQUEST_NOT_OPEN` ahead of the certificate checks — `routes/revocations.py`
- §3.1 — revise — ambiguity — `org_vetting_reuse_days` is optional (default 0), range depends on `validation_type` (`0..0` for DV, `1..825` otherwise); name uniqueness is case-folded — `routes/profiles.py:32,46-49,61-63`
- §3.1 — insert — ambiguity — retirement never rolls back revocation counters, CRL series state or `status_service_posture` — `routes/audits.py`, `services/cascade.py`
- §3.2 — revise — mismatch — subscribers are registered `ACTIVE`, not `PENDING_VETTING` — `routes/subscribers.py`
- §3.2 — insert — ambiguity — non-uppercase `jurisdiction_code` is `ERR_INVALID_REQUEST`; PATCH always touches even with no effective change — `routes/subscribers.py`
- §3.2 — insert — ambiguity — the credit-limit range check runs after subscriber lookup, so a bad id wins — `routes/subscribers.py`
- §3.3 — revise — mismatch — approval decides the dossier only; it writes nothing onto the subscriber (no vetting level, no activation) — `routes/subscribers.py`
- §3.3 — insert — ambiguity — `evidence_ref` is required but not stored; the dossier advances as soon as every required dimension is `PASSED` — `routes/subscribers.py`
- §3.4 — insert — ambiguity — challenge tokens are `dcv-challenge-%06d` from a global counter — `db.py` (`next_challenge_token`)
- §3.4 — revise — mismatch — token mismatch is diagnosed before the attempt ceiling; a miss at the ceiling lands in `EXHAUSTED`, not `FAILED` — `routes/authorizations.py`
- §3.4 — revise — mismatch — invalidate returns the authorization to `PENDING` with a fresh token; `reason` is required but discarded — `routes/authorizations.py`
- §3.5 — revise — mismatch — request creation checks only that the subscriber is `ACTIVE` (not the profile); a non-string domain entry is `ERR_INVALID_ARRAY_CONTENT`; projections stay null until clearance — `routes/requests.py:37-53,68-73`
- §3.5 — revise — mismatch — the three DCV diagnoses are three whole-list passes over all domains, not a per-domain walk — `routes/requests.py:174-206`
- §3.5 — revise — mismatch — org-vetting gates are set-based over all `APPROVED` files (any covering level, any fresh one) — `routes/requests.py:208-226`
- §3.5 — insert — ambiguity — candidate selection sorts `(validated_at, created_at, reuse_count, _seq)` descending; only the selected authorization's `reuse_count` increments — `routes/requests.py:202-206,235-237`
- §3.6 — revise — mismatch — a partition is registered `OPERATIONAL` carrying only `label` and `serial` (no firmware version, no slot) — `routes/partitions.py:22-41`
- §3.6 — revise — mismatch — ceremony scheduling gate order range → quarantine → window → conflict, with a 60-minute separation buffer — `routes/partitions.py`
- §3.6 — revise — mismatch — attestation gate order partition → `WITNESSED` → attester-was-witness → window-open — `routes/partitions.py`
- §3.6 — insert — ambiguity — revoke-attestation and abort require a `reason` that is discarded; the revoke cascade is four hops and only quarantines a currently-`OPERATIONAL` partition — `services/cascade.py`
- §3.7 — revise — mismatch — issuance gate order is profile → posture → subscriber → `READY_TO_ISSUE` → partition → SoD → ceremony → authorizations → supersedes → credit — `routes/requests.py:265-313`
- §3.7 — insert — ambiguity — `not_after` is the min of profile cap, authorization floor and attestation cap; `validity_days_final` floor-divides the span by 86400; `dcv_methods_used` is the sorted distinct set — `routes/requests.py:315-336`
- §3.7 — revise — mismatch — activation tests `lifecycle_status == EXPIRED` first, then shares `ERR_CERTIFICATE_NOT_PREISSUANCE` with the `revocation_status != NONE` case — `routes/certificates.py:99-130`
- §3.8 — insert — ambiguity — the conditional `evidence_ref` requirement precedes enum validation; certificate lookup precedes incident lookup — `routes/revocations.py`
- §3.8 — revise — mismatch — execution checks `ERR_REVOCATION_REQUEST_NOT_OPEN` first, then expired, then not-revocable; there is no "must be the newest `REQUESTED` request" precondition — `routes/revocations.py`
- §3.8 — insert — ambiguity — the refund fires only on a `PREISSUANCE` certificate revoked as `SUPERSEDED` — `routes/revocations.py`
- §3.8 — insert — ambiguity — denial releases the certificate's pending hold only when no other `REQUESTED` request remains against it — `routes/revocations.py`
- §3.8 — insert — ambiguity — CRL publication gate order stale-version → not-active → invalid-window → coverage-gap → not-advancing → too-long; drain sorted `(revoked_at, serial_number)`; the profile is touched twice when posture returns to `NOMINAL` — `routes/profiles.py:131-196`
- §3.9 — insert — ambiguity — incident birth field set, `disclosure_due_at = discovered_at + 24h`, and a risk recompute that lands on the value already held moves neither `version` nor `updated_at` — `routes/incidents.py`
- §3.9 — insert — ambiguity — disclosure answers 200 with the incident (not 201 with the communication); `within_deadline` is inclusive of the deadline instant — `routes/incidents.py`
- §3.9 — insert — ambiguity — batch-created requests are born `EXECUTED`/`MASS_REVOCATION` with null `evidence_ref`, `deadline_breached` false, and never supersede a pre-existing request — `routes/incidents.py`
- §3.9 — insert — ambiguity — penalty residual floors at 0 and is 0 outright on a non-positive denominator; per-certificate rounding precedes the sum — `services/calc.py`
- §3.9 — insert — ambiguity — the profile revocation ledger is updated per certificate inside the batch, and the posture flip touches the profile twice — `routes/incidents.py`, `services/cascade.py`
- §3.9 — insert — ambiguity — close reports both failing conditions as the single `ERR_INCIDENT_REVOCATIONS_OUTSTANDING` and answers 200 with the closed incident — `routes/incidents.py`
- §3.9 — revise — ambiguity — the audit period cap is an exact elapsed duration, so exactly 366 days is accepted; the period check precedes the already-open check — `routes/audits.py`
- §3.9 — insert — ambiguity — `summary` is required but never persisted; a finding always sets `state = FIELDWORK` and answers 200 with the audit — `routes/audits.py`
- §3.9 — revise — mismatch — opine accepts `SCHEDULED` as well as `FIELDWORK`, so a scheduled audit fails on `ERR_AUDIT_NO_FINDINGS` rather than `ERR_AUDIT_NOT_IN_FIELDWORK` — `routes/audits.py`
- §3.9 — revise — mismatch — assessed subscribers are walked in `created_at` order and scored unconditionally (still counted, still versioned, even on an unchanged score); the notice copies `root_program` from the audit with `body` null and `sent_by` `system`; the audit's `version` increments exactly once and the endpoint answers 200 with the audit — `routes/audits.py`
- §4 — revise — mismatch — profiles list also filters `status_service_posture` — `routes/profiles.py:96-99`
- §4 — revise — mismatch — four subscriber rows: created `ACTIVE`, filter is `jurisdiction_code`, read exposes account status (no vetting level), PATCH takes `credit_limit_cents`/`contact_email`/`callback_phone` — `routes/subscribers.py`
- §4 — revise — mismatch — three vetting rows: no stored reuse expiry, checks advance on required-dimension completion, approve writes nothing onto the subscriber — `routes/subscribers.py`
- §4 — revise — mismatch — four rows: validate ceiling → `EXHAUSTED`, invalidate → `PENDING` with a fresh token, request creation leaves projections null, request list filters `issued_certificate_id` — `routes/authorizations.py`, `routes/requests.py:79-89`
- §4 — revise — mismatch — certificates list filters request/ceremony/supersedes and has no serial filter — `routes/certificates.py:19-27`
- §4 — revise — mismatch — CT submissions sort by `created_at` and filter by `outcome`; no `submitted_at` field exists — `routes/certificates.py:90-96`
- §4 — revise — mismatch — five HSM rows: created `OPERATIONAL` with `serial`+`label`, filtered/read on `state`, attested ceremony count, one-hour ceremony buffer, ceremony list filters `state` — `routes/partitions.py:22-108`

**Orchestrator verification:** `PRD_COMPLETED.md` is NOT byte-identical to `PRD_FINALIZED.md` (128 differing lines across 52 hunks, +12,831 bytes at identical 497-line count), and the file ends on the final §5 error-table row — the scan genuinely ran and the output is not truncated.

## Pipeline complete — 2026-09-03T20:15:44.282Z

All 9 steps done. Final artifacts: `SCAFFOLD.yaml`, `SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`, `test_helpers/` (9 modules), `test_suite/` (18 test files, 168 collected tests), `workspace/{INSTRUCTION.md,PRD.md,PRD_FINALIZED.md,PRD_COMPLETED.md}`, `workspace/implementation/` (22 modules, 64 endpoints, `start.sh`), `workspace/implementation/results.{1..8}.json` (all 168/168).
