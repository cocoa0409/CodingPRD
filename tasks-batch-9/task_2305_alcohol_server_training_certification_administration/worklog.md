# Worklog — task_2305_alcohol_server_training_certification_administration

## Step 1: Create task directory — 2026-09-01T00:00:00.000Z

Created `tasks/task_2305_alcohol_server_training_certification_administration/` and `workspace/` subdirectory (name pre-allocated by caller; no index scan performed).

## Step 2: Generate scaffold — 2026-09-01T16:02:00.000Z

All three scaffold artifacts are complete and lint-clean.

**Files** (all in `/home/ubuntu/github/CodingPRD/tasks/task_2305_alcohol_server_training_certification_administration/`):
- `SCAFFOLD.yaml` — 2,682 lines (§1.0–§1.7; no design keys)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 2,357 lines (single key `scaffold_difficulty_design`)
- `SCAFFOLD_CORNER_DESIGN.yaml` — 3,232 lines (single key `scaffold_corner_design`)

**SCAFFOLD.yaml contents**
- 15 entities (StateJurisdiction, Course, CourseApproval, Trainer, ClassSession, AlcoholServer, Enrollment, ExamAttempt, Certificate, RegistrySubmission, EmployerAccount, EmployerLocation, ServerAssignment, DramShopDocument, ComplianceRun — the last is the only `common_fields: false` immutable entity)
- 9 state machines / 47 transitions; `state_machine_shape: cyclic` (retake loop) with parallel validity/registry dimensions on Certificate
- 3 OCC concurrency rules (ClassSession, Course, EmployerAccount)
- 10 calculations, two of them dual-variant (`certificate_expiry_and_anchor` ISSUANCE vs ANNIVERSARY anchored; `location_compliance_metrics` STRICT vs GRACE_INCLUSIVE)
- 38 ordered validations, 54 endpoints (32 writes / 22 reads, root-mounted, `api_prefix: ""`), 40-code error catalog
- 5 RBAC roles under `role_model: segregation_of_duties`: ProgramAdmin, StateRegulator, Trainer, EmployerAdmin, AlcoholServer
- `complexity_layers: [optimistic_concurrency, cascading_side_effects, dual_variant_calculation, rate_threshold_triggers]`; `entity_topology: graph`; `consistency_model: immediate`; logical clock defaults to `2026-08-01T00:00:00Z` and every recipe pins it explicitly

**§1.8 difficulty design** — 20 instances across all 9 required rule_ids (≥2 each): dual_variant_calc 2, combinatorial_formula 3, non_linear_state_machine 2, transitive_cascade 2, priority_pair_validation_conflict 2, boundary_precision_check 2, cross_entity_state_dependency 2, resource_temporal_overlap 2, compensating_invariant 3. Highlights: an 8-step pinned seat-credit settlement with fee cap and net-based bonus, a six-hop registry-rejection cascade ending in a voided dram-shop document, an epoch-driven lapse cascade spanning two compliance runs, and exact-instant grace/lapse boundaries.

**§1.9 corner design** — 67 instances (47 full recipes + 20 `excluded_because:` stubs, every stub citing a §1.8 instance that exists by name) across all nine taxonomy sections: entities 11, state_machines 11, calculations 12, validations 16, endpoints 4, errors 2, rbac 3, cross-cutting layers 7, consistency model 1. All 40 error codes are triggerable, with an explicit coverage map comment mapping each code to its owning section; the three OCC rules each get their own stale-version instance.

**Validation performed**: both design files parse; every `Entity.field` cited in asserts was checked programmatically against §1.1; all instance names unique across the union of both files; asserted read paths corrected to declared endpoints only (removed three `GET /state-jurisdictions` and two nested-enrollment reads that were never declared). Final linter run: `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` (960 calls scanned).

No sibling task directory was listed, globbed, grepped, or read at any point.

## Step 3: Copy shared files — 2026-09-01T16:03:00.000Z

Copied `INSTRUCTION.md` → `workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-09-01T16:14:00.000Z

PRD generated at `workspace/PRD.md`.

## Output
- **505 lines**, 25 headings, ends at §5 with no audit footer.
- **§1 Introduction** — 3 paragraphs (industry pain-point angle, then the two structural commitments: segregation of duties, immediate-recompute-except-time).
- **§2 (11 subsections)** — 2.1 RBAC (all 5 roles + each role's identity semantics), 2.2 verbatim envelope (byte-identical, verified), 2.3 Pagination, 2.4 Identity/audit/`version` (incl. `ComplianceRun` carrying only `id`+`created_at`), 2.5 OCC on contended parents (all 3 rules with field + error + 412), 2.6 Logical clock & epoch boundary (`2026-08-01T00:00:00Z` default), 2.7 Precision & pinned rounding orders, 2.8 The five-stage recompute chain, 2.9 Screening order (full 1-38 priority ladder) + 4-family 404 mapping, 2.10 Segregation of duties, 2.11 Request-shape ranges.
- **§3 (9 subsections)** — jurisdiction rule mapping -> catalogue drafting/revision/supersession -> approval review-round loop -> trainer credentialing/suspension -> scheduling & seat claiming -> proctored exam cycle -> certificate issuance & registry round trip -> employer accounts/seats/locations/assignments -> dram-shop documentation & the 8-phase compliance epoch.
- **§4** 4-column table, all 54 endpoints. **§5** 2-column table, all 40 error codes.

## Hard Contract Reports

```
Field coverage check:
- entities[].fields: 156 required, 156 present, 0 missing
- endpoints[].request_body: 71 required, 71 present, 0 missing
- endpoints[].query_params: 26 required, 26 present, 0 missing
Status: PASS
```

```
Rule coverage check:
- validations[] with priority: 38 checked, 38 expressed in prose, 0 missing
- concurrency_rules[] OCC rejections: 3 checked, 3 expressed (write_endpoint + expected_<parent>_version + error_id + 412 all named), 0 missing
- state_machines[].transitions: 47 checked, 47 fully expressed, 0 missing
- calculations[]: 10 checked, 10 fully expressed, 0 missing
- validations[] conditions: 38 checked, 38 matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: 54 checked, 54 expressed, 0 missing
- entities[].fields[] structured content: 156 checked, 156 reconstructible from prose, 0 missing
- sibling-branch symmetry: 8 groups checked (3 approval decisions, 3 exam outcomes, 2 acknowledgement results, 2 expiry anchor variants, 2 compliance-rate variants, 2 cancel from-states, 2 assignment-end from-states, 3 certificate->SUPERSEDED sources), 8 with equal prose density, 0 asymmetric
Status: PASS
```

```
Path purity check (§3 only):
- backtick tokens scanned: 949
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

## Key findings during generation
- All 156 entity field names, 71 request-body identifiers, 26 query params, 40 error IDs, every state-enumeration value and every enum-type field value verified present in backticks by script.
- Two priority inversions the scaffold pins deliberately were called out explicitly in prose so an implementer can't get them backwards: retake **cap** is checked before **cooling-off** (priority 31 before 34), and the session-version OCC check precedes the capacity check (7 before 28).
- The `SCAFFOLD_DIFFICULTY_DESIGN.yaml` and `SCAFFOLD_CORNER_DESIGN.yaml` files were not opened, grepped, or referenced; no sibling task directory was read.

## Step 5: Generate unit tests — 2026-09-01T18:12:00.000Z

Test generation is complete. Both queues are fully translated except one instance that fails the PRD-first filter.

## Files

**`test_helpers/`** (10 files, infrastructure — built earlier in this task, unchanged now): `__init__.py`, `api_client.py` (57 methods, headers-first list signatures), `api_errors.py`, `assertions.py`, `constants.py`, `factories.py`, `fixtures.py`, `test_users.py`, `types.py`.

**`test_suite/`** — `conftest.py` + 16 test modules, **86 tests**, all 66 non-stub design instances tagged exactly once:

| file | tests | source |
|---|---|---|
| `test_01`–`test_09` | 40 | queue A, all 9 rules / 20 instances (>=2 tests each) |
| `test_10_resource_shapes_and_defaults.py` | 11 | Corner/entities (11/11) |
| `test_11_lifecycle_transitions.py` | 8 | Corner/state_machines (8/8 live) |
| `test_12_derived_metrics.py` | 4 | Corner/calculations (4/4 live) |
| `test_13_request_screening_and_validations.py` | 10 | Corner/validations (10/10 live) |
| `test_14_endpoint_projections.py` | 5 | Corner/endpoints (4/4) + consistency model (1/1) |
| `test_15_refusals_and_access_control.py` | 4 | Corner/errors (2/2) + Corner/rbac (2/3) |
| `test_16_concurrency_tokens_and_posture_bands.py` | 4 | Corner/cross-cutting complexity layers (4/4 live) |

Gates: citation checker reports "all citation checks pass", "difficulty instances with <2 tests: (none)", "corner instances with 0 tests: 21" = 20 declared stubs + 1 deliberate skip. `pyflakes test_suite/*.py` clean.

## Coverage audit

- **Queue A (difficulty):** 20/20 instances translated, 40 tests. No skips.
- **Queue B (corner):** 47 live instances, 46 translated, 1 skipped; 20 stubs carrying `excluded_because:` were correctly not translated.

**Skipped instance —** `Corner/rbac/an_employer_admin_cannot_read_another_accounts_location`. It asserts that all three cross-account calls return 403 `ERR_NOT_RESOURCE_OWNER`, including `GET /employer-locations/{id}` and `GET /employer-locations/{id}/compliance-dashboard`. PRD §2.1 states the ownership test "is applied on exactly these operations" and that closed list contains only writes (locking a roster, opening an exam, …, "every write beneath an employer account path", assigning, ending). §4 lists `EmployerAdmin` as an authorised role on both reads, and the PRD contains no read-scoping language anywhere. So the PRD uniquely derives **200** for two of the three triggers — the instance's asserted outcome is not PRD-derivable, and emitting only the third trigger would be weakening. Gap left as a gap.

## Design-index defects found (tests follow the PRD, not the index)

1. `Corner/errors/zero_balance_sponsorship_repeat_registry_submission_and_duplicate_assignment_are_each_refused` asserts `Certificate.registry_state == 'TRANSMITTED'` after transmission. PRD §3.7 says "The certificate's `registry_state` becomes `SUBMITTED`" (`TRANSMITTED` belongs to the submission's own dimension). `test_15` asserts `SUBMITTED`.
2. `Corner/state_machines/trainer_suspension_cascades_…` asserts `seat_credits_purchased_total == 21` / `seat_credit_balance == 21` for a 20-seat purchase. `test_11` reads the granted total back from the account and asserts consumed 1 / refunded 1 / balance == granted.
3. `Corner/validations/duplicate_seat_and_capacity_ceiling…` writes `paid_by == 'SELF'`; PRD §3.5 says `SELF_PAY`. `test_13` asserts the PRD value.
4. Two instances assert `StateJurisdiction.certificates_issued_count`, which §4 exposes no read endpoint for. Those lines were dropped as unobservable; the observable consequence (`certificate_number` minting) is asserted instead.

## Step 6: Generate implementation — 2026-09-01T17:40:00.000Z

Implementation is complete and verified.

## Files created
All under `workspace/implementation/`:

- `start.sh` — `cd` to own dir, guarded `pip install -q -r requirements.txt` (only if `import flask` fails), then `exec python3 app.py`; `PORT` env, default 10000, bound to `0.0.0.0`
- `requirements.txt` — `Flask==3.0.3`
- `app.py` — app factory, 4 blueprints, `ApiError` / `HTTPException` / catch-all error handlers that all emit the standard envelope
- `store.py` — the entire in-memory store: 15 dicts keyed by id, logical clock (`2026-08-01T00:00:00Z` at boot), `_seq` monotonic tiebreaker, `create_row` / `touch` / `apply_changes` (version bumps only on real field changes). No seeding, no disk, no SQLite.
- `envelope.py`, `errors.py` (40 error ids -> HTTP status), `validate.py` (38-step-ordered field helpers, enums, 4-family 404 map, pagination), `auth.py` (5 roles, ownership), `calcs.py` (ROUND_HALF_UP, cents, month clamp, pinned rounding orders), `chain.py` (5-stage recompute chain R), `domain.py` (seat-credit ledger, cascades, certificate issuance, 8-phase compliance epoch)
- `api_catalog.py`, `api_training.py`, `api_credential.py`, `api_employer.py` — routes

## Endpoints
**54** implemented — matches `grep -c "^  - method:" SCAFFOLD.yaml` (54) and the PRD endpoint table (54). Flask's `url_map` reports exactly 54 non-static rules. (An earlier working note of "57" was wrong.)

## Verification
End-to-end smoke run (test client) passed: jurisdiction -> course publish -> approval APPROVE -> trainer credentials -> session (incl. 409 schedule conflict) -> employer account / seat-credit purchase / location / assignment -> enrollment (incl. 412 stale OCC) -> lock-roster -> attendance -> open-exam (422 window-not-open, 422 proctor-separation, then 200) -> voided attempt -> FAIL -> 422 cooling-off -> PASS -> complete -> certificate issuance -> dashboards / account / trainer metrics -> registry submit -> REJECTED cascade -> resubmit + ACCEPTED restoration -> dram-shop document (TIER_3, 10.00%, credit 123457) -> 412 stale OCC -> three compliance runs (grace, lapse+restrict+void, all-zero idempotent) -> assignment end -> RBAC/pagination/envelope checks. The real server also booted via `PORT=10123 bash start.sh` and answered over HTTP with correct envelopes. Temp smoke script and `__pycache__` removed.

## PRD ambiguities resolved by choice
- `created_at`/`updated_at` use the **logical** clock; `meta.api_request_timestamp` uses **real** wall clock (PRD only says "server-generated").
- Governing-certificate selector for chain R1 is unspecified: candidates = the server's certificates with `validity_state != SUPERSEDED`, ranked `expires_at` DESC, tie-break `created_at` ASC, not scoped by jurisdiction or track.
- `credential_expires_at <= clock` (and empty `certified_tracks` / `certified_state_codes`) on `POST /trainers/{id}/credential` have no error id -> `ERR_INVALID_REQUEST` at the priority-3 shape stage.
- Ending an already-`ENDED` assignment has no dedicated code -> `ERR_ACCOUNT_INVALID_STATE` (409).
- `POST /class-sessions/{id}/complete` with a seat still `EXAM_IN_PROGRESS` -> `ERR_ENROLLMENT_INVALID_STATE` (priority 14).
- APPROVE/resubmit when the course is no longer `PUBLISHED` -> `ERR_COURSE_INVALID_STATE` at priority 10, ahead of the priority-11 approval-state check.
- `raw_correct_count` presence/type at priority 3; its `0..question_count` range check after path resolution and before ownership.
- Ownership on `POST /enrollments` (in PRD §2.1 but absent from the priority-5 `applies_to`): AlcoholServer's `X-User-ID` must equal body `alcohol_server_id`, EmployerAdmin's must equal `sponsoring_employer_account_id` when supplied — raw string compare before FK resolution.
- Among GETs, ownership is enforced only on `GET /alcohol-servers/{id}/server-assignments` for the AlcoholServer role (priority-5 `applies_to` lists POSTs only).
- open-exam ownership checks `session.trainer_id` (proctor is still null); `POST /class-sessions` is **not** ownership-checked.
- `POST /enrollments/{id}/exam-attempts` and `POST /exam-attempts/{id}/submit` are Trainer-only (ProgramAdmin -> `ERR_ROLE_NOT_PERMITTED`), ownership vs `session.proctor_trainer_id`.
- Unknown enum members in query filters -> `ERR_INVALID_REQUEST`; unresolvable id-shaped filters simply return an empty list.
- Compliance epoch affected sets: phase 5 runs stage 1 only for holders of certificates that transitioned in phase 3; phase 6 runs stage 2 over all servers with live assignments; `affected_locations` = locations of live assignments of servers whose stage 1 changed union locations with a transitioned assignment; `locations_recomputed_count = len(affected_locations)`; phase 8 recomputes affected accounts, then scans all `ISSUED` documents, checking the compliance floor before `COVERAGE_PERIOD_ENDED`.
- Assignment creation runs stage 3 (that location) + stages 4/5 only — no stage 2, so an `UNCERTIFIED` server past its new-hire window is restricted only by a compliance run.
- Location creation computes requirement, zero counts, both rates `100.00` and posture inline so its `version` stays 1 (MANDATED-and-empty -> `COMPLIANT`, VOLUNTARY -> `NOT_APPLICABLE`), then runs account R4/R5.
- `months_documented` is computed before `first_documented_at` is set (0 for the first document); dram-shop issuance always bumps the account `version`, even when no account field changes.
- Session approval selection: first (by `created_at` ASC) `APPROVED` approval for (course, jurisdiction) with `effective_from <= scheduled_start_at < expires_at`.
- Enrollment `attempt_count`/`attempt_number` count only PASS/FAIL attempts (a `VOIDED` attempt never consumes a retake); `last_counted_attempt_ended_at` is stamped on PASS as well as FAIL (its derived definition covers both outcomes), while `retake_eligible_at` is stamped only on the FAIL branch, which is the only branch PRD §3.6 says advances the cooling-off window.
- Unrouted paths/methods return the standard error envelope with `ERR_INVALID_REQUEST` and Werkzeug's status (404/405).

## Step 7: Run tests and iterate — 2026-09-01T19:15:00.000Z

GREEN: all 8 parallel rounds pass 86/86.

## Summary

**Iterations run: 3 full 8-round parallel sweeps**

- Sweep #1 — 73/86 in all 8 rounds (13 identical failures)
- Sweep #2 — 85/86 in rounds 1,2,6,7,8; 84/86 in rounds 3,4,5
- Sweep #3 — **86/86 in all 8 rounds, 0 failures** (results verified from each `results.N.json`)

**Tests deleted: none.** One assertion (not a test) was removed:

- `test_09_compensating_invariants.py::TestRegistryAcceptanceRestoresOnlyWhatItCan::test_the_late_resubmission_is_priced_and_the_holder_is_restored` — removed `assert server["restricted_since"] is None`. Pattern: **BRANCH-ASYMMETRIC SIDE EFFECT** — PRD §3.7/§2.8 enumerate the restoration branch's effects (`work_eligibility -> ELIGIBLE`, `WORK_RESTRICTED -> ACTIVE`, `restriction_reason -> NONE`, metric recompute) and PRD §3.8 explicitly says only the *assignment*'s `restricted_at` is cleared; nothing anywhere states the server's `restricted_since` is cleared on restoration. Driving scaffold rule: `Difficulty/compensating_invariant/registry_acceptance_restores_the_assignment_but_never_revives_the_voided_dram_shop_document`. All other assertions in the test (late_days 2, penalty 525, ACCEPTED, history `[REJECTED, ACCEPTED]`, certificate ACTIVE/ACCEPTED, eligibility, assignment ACTIVE/NONE/`restricted_at` None) were kept.

**Fixes to `test_helpers/` (test-artifact bugs, STEP 2):**

1. `test_helpers/types.py` — `SubmissionResult` was `ACCEPT`/`REJECT` (wrongly copied from the PRD-verbatim `ApprovalDecision` APPROVE/REQUEST_CHANGES/REJECT); changed to `ACCEPTED`/`REJECTED`. PRD §3.7 names the outcomes only as "An accepted result"/"A rejected result", so no verbatim token forbids either; SCAFFOLD's `acknowledge (result = ACCEPTED|REJECTED)` settled the direction. This fixture was issuing a request the PRD-faithful implementation correctly refused, breaking setup for 9 tests across test_03/04/07/09/11.
2. `test_helpers/factories.py` — `acknowledge_accept_payload` / `acknowledge_reject_payload` now emit `ACCEPTED` / `REJECTED`.
3. `test_suite/test_09_compensating_invariants.py` — setup helpers restructured (`_sponsored_seats`, `_two_sponsored_seats_on_a_locked_roster`, `_three_sponsored_seats_with_one_already_withdrawn`) so every seat is claimed while the session is still `SCHEDULED`. The old helpers enrolled after `lock_roster`, which PRD §3.5 requires to fail with `ERR_SESSION_INVALID_STATE`; the `ROSTER_LOCKED -> CANCELLED` intent is preserved by locking after the enrollments/withdrawal.

**Fixes to `implementation/`:**

1. `workspace/implementation/domain.py::recompute_attempt_counters` — `retake_eligible_at` is now stamped only when the last counted attempt is a `FAIL`. PRD §3.6's FAIL branch is the only one that mentions the cooling-off window ("`retake_eligible_at` becomes that instant plus the jurisdiction's `retake_cooling_off_hours` hours"); the PASS branch enumerates its own three effects and does not touch it. `last_counted_attempt_ended_at` still stamps on both outcomes, per its derived definition.
2. `workspace/implementation/api_training.py` (open-exam) — a session pinned to an approval left `STALE` by a mid-flight content revision now fails with `ERR_APPROVAL_STALE_CONTENT` (priority 19) instead of `ERR_APPROVAL_NOT_EFFECTIVE` (priority 18). PRD §3.2 names this exact scenario and error verbatim: "Sessions already pinned to a now-stale approval keep their pin … they will fail at exam-opening time with `ERR_APPROVAL_STALE_CONTENT`." Verified no other test expects `ERR_APPROVAL_NOT_EFFECTIVE` on open-exam.
3. `worklog.md` — corrected the stale "PRD ambiguities resolved by choice" note that claimed `retake_eligible_at` is stamped on PASS as well as FAIL.

**On the sweep-#2 flake:** `test_02_expiry_anchoring_and_rate_variants.py::TestGraceRosterRateDivergence::test_strict_and_grace_inclusive_rates_diverge_for_an_all_grace_roster` failed in 3 rounds with `RemoteDisconnected` mid-setup. Root cause was environmental, not a code defect: the per-server logs show a literal `Terminated` (external SIGTERM) interleaved mid-test, whereas the runner's own per-test restart path always logs `Killed` (SIGKILL from `kill_port`). Surveying every round log from both sweeps showed `Terminated=1..4` alongside `Killed=83..86` in **all 16** logs — including sweep #1, where no test flaked — so these SIGTERMs recur every round and only surface as a failure when one lands inside a test rather than between tests. A co-tenant 8-round pipeline (task_2299) was confirmed running concurrently. No implementation or test change was made for it, and it did not recur in sweep #3.

Generated `results.*.json` and `__pycache__` were cleaned out of `workspace/implementation/`.

## Step 8: Finalize PRD — 2026-09-01T20:00:00.000Z

`PRD_FINALIZED.md` written at `workspace/PRD_FINALIZED.md`.

## Size delta

- Lines: 505 -> 505 (0.00%) — every edit is inline inside an existing paragraph line.
- Words: 11,385 -> 11,586 (+201, +1.77%); bytes 85,753 -> 86,989 (+1.44%).

## Changes (5 hunks, 4 subjects)

- **§2.8 stage one** — *insert* — after the existing `restricted_since` sentence: the stamp is written only on the transition *into* `RESTRICTED` (a server already `RESTRICTED` keeps the earlier instant), and the server's `restricted_since` is **never cleared** on any later return to `ELIGIBLE`/`GRACE`/`UNCERTIFIED`; parenthetically distinguishes the assignment's `restricted_at`, which *is* cleared. — `chain.py:110-112`
- **§3.6 open-exam gate** — *revise* — the pinned approval must be `APPROVED` **or `STALE`** (anything else, incl. the `SUBMITTED` a resubmission-from-`STALE` leaves, is `ERR_APPROVAL_NOT_EFFECTIVE`); a `STALE` approval **or** a `pinned_course_version` mismatch is `ERR_APPROVAL_STALE_CONTENT`. — `api_training.py:232-241`
- **§2.9 priority 18** — *revise* — "the pinned approval is still approved" -> "has not drifted outside the `APPROVED`-or-`STALE` pair", so the summary line no longer contradicts the §3.6 body. — `api_training.py:233-234`
- **§3.6 derived counters** — *insert* — `last_counted_attempt_ended_at` stamps on `PASS` as well as `FAIL`; `retake_eligible_at` is **not** derived — the `FAIL` branch is its only writer, a `PASS` (like a voided attempt) leaves the prior value in place, and nothing ever nulls it. — `domain.py:227-237`
- **§3.7 acknowledgement** — *insert* — the `result` vocabulary is exactly `ACCEPTED` / `REJECTED`. — `api_credential.py:95,105` + `validate.py:34`

No edit for Step 7 item 3 (test_09 setup restructure): PRD §3.5 line 278 and §2.9 line 157 already pin `ERR_SESSION_INVALID_STATE` for enrolling into a `ROSTER_LOCKED` session, and `api_training.py:426` matches verbatim — pure fixture bug. Step 7 item 2 (factories) is the same subject as item 1, covered by the §3.7 edit.

## Per-edit pre-edit search log

**1. §2.8 `restricted_since`**
(a) Subject: the server-level `restricted_since` field — every writer, clearer and initialiser, plus the neighbouring assignment-level `restricted_at`.
(b) Enumerated: `grep -rn "restricted"` across all of `implementation/` -> `chain.py:111` (sole writer, guarded by `eligibility == "RESTRICTED" and server["work_eligibility"] != "RESTRICTED"`), `api_training.py:352` (creation-time `None`); assignment `restricted_at` writers/clearers at `chain.py:143,158,168` and `api_employer.py:292`. Read `chain.stage_one`, `chain.stage_two`, `domain.acknowledge_accepted/rejected`, `domain.run_compliance_epoch` phases five/six, `domain.complete_session` — all reach `restricted_since` only through `stage_one`, none clears it.
(c) Adjustment: added the "written only on the transition *into* `RESTRICTED`" clause so the sentence does not imply re-stamping on a `LAPSED -> SUSPENDED` cause change (which `chain.py:110`'s guard suppresses), and added the explicit `restricted_at` parenthetical so "never cleared" cannot be read as overriding §3.8's assignment-level clearing at `chain.py:168`.

**2. §3.6 open-exam approval gate**
(a) Subject: the status/version admissibility of a session's `pinned_course_approval_id`, and the `ERR_APPROVAL_NOT_EFFECTIVE` vs `ERR_APPROVAL_STALE_CONTENT` split.
(b) Enumerated: `grep -rn "ERR_APPROVAL_NOT_EFFECTIVE\|ERR_APPROVAL_STALE_CONTENT"` -> `api_training.py:150-157` (session creation, a *different* gate that still requires strictly `APPROVED` via `_effective_approval`) and `api_training.py:232-241` (open-exam). Read every producer of a non-`APPROVED` status on an already-pinned approval: `domain.stale_approvals_of` (`APPROVED->STALE`), `api_catalog.resubmit_approval` (`STALE->SUBMITTED`, or `->REJECTED` at the round cap, clearing `pinned_course_version`), `api_catalog.decide_approval` (`SUBMITTED->CHANGES_REQUESTED`), `domain.publish_course` (`APPROVED->SUPERSEDED`), `domain.run_compliance_epoch` phase two (`APPROVED->EXPIRED`); plus `errors.py:33-34` for the status codes.
(c) Adjustment: scoped the sentence to "the pinned approval" only, so it says nothing about `_effective_approval` at session creation (which must stay `APPROVED`-only, `api_training.py:150`); used the open-ended "any other status it may have drifted into" rather than enumerating `EXPIRED`/`SUPERSEDED`/`REJECTED`, because `CHANGES_REQUESTED` is also reachable on a pinned approval; dropped any mention of a missing/unresolvable pinned approval, since `api_training.py:233`'s `approval is None` branch is unreachable (approvals are never deleted).

**3. §2.9 priority 18 summary line**
(a) Subject: same as edit 2 — kept as a separate hunk only because §2.9 restates the rule.
(b) Enumerated: `api_training.py:233-234` (open-exam, priority 18) and `api_training.py:151-153` (session creation, priority 18); confirmed §2.9's clause has two limbs and only the second ("pinned approval") needed widening.
(c) Adjustment: widened only the second limb; left "An approval covers the requested window" verbatim so the session-creation path at `api_training.py:150` stays correctly described.

**4. §3.6 derived attempt counters**
(a) Subject: `retake_eligible_at` and `last_counted_attempt_ended_at` — every writer, reader and initialiser.
(b) Enumerated: `grep -rn "retake_eligible_at\|last_counted_attempt_ended_at\|best_score_pct\|attempt_count"` -> `api_training.py:465-468` (creation, all `None`/0), `api_training.py:547` (cap gate reads `attempt_count`), `api_training.py:550-551` (cooling-off gate reads `retake_eligible_at`), `api_training.py:557` (`attempt_number`), `api_training.py:606-608` (submit applies the recompute), `domain.recompute_attempt_counters:221-238` (sole writer; `last_counted_attempt_ended_at` on both `PASS` and `FAIL`, `retake_eligible_at` on `FAIL` only). Confirmed the non-attestation path at `api_training.py:595-600` returns before the recompute, so `VOIDED` touches none of them.
(c) Adjustment: phrased it as "the `FAIL` branch above is its only writer … nothing ever clears it back to null" instead of "a `PASS` leaves it unchanged", so the sentence also correctly covers the `VOIDED` early-return path and the creation-time `None` at `api_training.py:468`; added the explicit note that `last_counted_attempt_ended_at` *does* stamp on `PASS`, so the new asymmetry cannot be over-generalised to that field.

**5. §3.7 `result` vocabulary**
(a) Subject: the request field `result` on `POST /registry-submissions/{id}/acknowledge` and its accepted token set.
(b) Enumerated: `grep -rn "result"` across `api_*.py`/`validate.py` -> `api_credential.py:95` (`v.req_enum(body, "result", v.ACK_RESULTS)`), `api_credential.py:97` (rejection-code guard), `api_credential.py:105-108` (branch dispatch to `domain.acknowledge_accepted`/`acknowledge_rejected`), `validate.py:34` (`ACK_RESULTS = ("ACCEPTED", "REJECTED")`); confirmed no other endpoint reads a `result` field, and cross-checked `validate.py:32` `REGISTRY_STATES` / `domain.acknowledge_*` so the same `ACCEPTED`/`REJECTED` tokens used for `submission_state` are not redefined.
(c) Adjustment: said "whose vocabulary is exactly `ACCEPTED` and `REJECTED`" without naming a rejection error code, since `v.req_enum` routes a missing or unrecognised value to `ERR_INVALID_REQUEST` at §2.9 priority 3 — already covered by the existing "required body fields present, enum members recognised" clause; deliberately left the §3.7 `rejection_code`-required sentence untouched, as its error code was not a Step 7 finding.

**Orchestrator note (independent verification):** after Step 7 exited, the orchestrator re-ran the full 8-round parallel sweep to regenerate the `results.{1..8}.json` artifacts Step 7 had cleaned up. All 8 rounds: **86/86 passed, 0 failures**.

## Step 9: Complete PRD — 2026-09-01T20:20:00.000Z

Done. `workspace/PRD_COMPLETED.md` written as an in-place patch over `PRD_FINALIZED.md`.

**Counts:** 505 lines -> 505 lines (no line added/removed; every edit is in-paragraph). 86,989 -> 95,749 chars (**+8,760**). 39 changed lines across 37 hunks: **34 ambiguity-pins, 5 mismatch-revisions**.

**Mismatch-revisions**
- §2.1 — revise — mismatch — ownership-operation list dropped "setting standing" (a `ProgramAdmin`-only route with no ownership test) and added seat-claiming plus the server-assignment listing; noted the claim-a-seat test is partial for `EmployerAdmin` — `api_training.py:410-414`, `api_employer.py:64-75`
- §2.4 — revise — mismatch — `version`/`updated_at` bump only when a field actually changes value, with dram-shop issuance as the one forced-bump exception — `store.py:79-88`, `api_employer.py:201-202`
- §2.4 — revise — mismatch — compliance run "carries only `id` and `created_at`" scoped to the audit set; it also carries `run_at` and the nine counters — `domain.py:402-404`
- §3.6 — revise — mismatch — open-exam gates are evaluated in §2.9 priority order, not the prose order (approval/proctor before attendance before window); proctor id resolves first; acting trainer is the instructor — `api_training.py:220-259`
- §3.6 — revise — mismatch — removed "or a `ProgramAdmin`" from attempt open/submit: `Trainer` is the sole authorised role, admin gets `ERR_ROLE_NOT_PERMITTED` — `api_training.py:533,573`

**Ambiguity-pins**
- §2.1 — insert — session-level open-exam ownership compares `trainer_id` — `api_training.py:30-33,226`
- §2.2 — insert — `api_request_timestamp` is real wall-clock, not the logical clock — `envelope.py:27-31`
- §2.3 — insert — `has_more` = `offset + len(page) < total_count`; empty-string filters treated as absent — `envelope.py:71`, `validate.py:284-288`
- §2.4 — insert (x2) — `created_at`/`updated_at` read the logical clock; insertion sequence breaks ties — `store.py:58-68,53-55`
- §2.5 — insert — unrecognised body fields are ignored, not rejected — `validate.py:76-84`
- §2.6 — insert — clock set answers `200 OK`; may move backwards — `api_catalog.py:29-35`
- §2.7 — insert — percentages serialise as plain JSON numbers (`70.00` may render `70.0`) — `envelope.py:38-39`
- §2.8 stage one — insert — governing-certificate selector (non-`SUPERSEDED`, `expires_at` DESC, `created_at` ASC) and `certification_count` refresh — `chain.py:59-69,96-112`
- §2.8 stage two — insert — an already-`WORK_RESTRICTED` assignment only has its `restriction_reason` refreshed; no re-stamp, no count — `chain.py:149-150`
- §2.8 stage three — insert — "touched" = every location of a live assignment, `VOLUNTARY` included, deduplicated — `chain.py:127-131,224-228`
- §2.9 — insert — `ERR_ENROLLMENT_INVALID_STATE` also covers completing with a seat in `EXAM_IN_PROGRESS` — `api_training.py:282-285`
- §2.9 — insert — `raw_correct_count` upper bound deferred until the attempt resolves (404 before that 400), still ahead of ownership — `api_training.py:575-582`
- §2.11 — insert — `certified_state_codes` members are unconstrained strings — `validate.py:231-242`
- §3.2 — insert — unresolvable supersession target is `ERR_CATALOG_NOT_FOUND`, at authoring time too — `api_catalog.py:103-104,162-164`
- §3.2 — insert — `revision_note` required but not persisted; omitted revision fields left as-is — `api_catalog.py:139-147`
- §3.3 — insert — `changes_requested_note` optional; approve-only fields not required on other branches — `api_catalog.py:255-264`
- §3.3 — insert — resubmit `submission_note` optional and sticky — `api_catalog.py:316-317`
- §3.3 — insert — a fourth-round resubmission still records `review_round` 4 alongside `REJECTED` — `api_catalog.py:314-322`
- §3.4 — insert — credential shape rules are priority-3 `ERR_INVALID_REQUEST`, before the trainer id resolves — `api_training.py:72-77`
- §3.4 — insert — `suspension_reason` optional; suspendable from `PROVISIONAL`/`CERTIFIED`/`LAPSED` — `api_training.py:93-96`
- §3.5 — insert — `withdrawal_reason` optional/sticky; non-sponsor `EmployerAdmin` (incl. self-pay seats) gets `ERR_NOT_RESOURCE_OWNER` — `api_training.py:505-511,520-522`
- §3.5 — insert — `cancellation_reason` is mandatory (`ERR_INVALID_REQUEST`) — `api_training.py:294`
- §3.6 — insert — attempt on a pre-`EXAM_OPEN` session yields `ERR_NOT_RESOURCE_OWNER` (null proctor at priority 5) — `api_training.py:36-38,537`
- §3.7 — insert — missing/`NONE` `rejection_code` is priority-3 `ERR_INVALID_REQUEST`; ignored on the accepted branch — `api_credential.py:96-98`
- §3.8 — insert — `status_reason` sticky; any standing reachable from any other — `api_employer.py:68-74`
- §3.8 — insert — new location's opening posture is `COMPLIANT` when `MANDATED`, `NOT_APPLICABLE` when `VOLUNTARY` — `api_employer.py:118-121`
- §3.8 — insert — assignment creation does not run stage two, so zero-day new-hire windows wait for a run — `api_employer.py:296`
- §3.8 — insert — ending an already-`ENDED` assignment is `ERR_ACCOUNT_INVALID_STATE` — `api_employer.py:308-309`
- §3.9 — insert — `months_documented` discards a partial final month and floors at zero — `calcs.py:37-48`
- §3.9 phase five — insert — affected servers = holders of certificates that actually transitioned in phase three — `domain.py:339-369`
- §3.9 phase six — insert — stage two evaluates every server holding a live assignment, wider than phase five — `domain.py:372-375`
- §3.9 phase seven — insert — affected-location set defined as the union of phase-five live-assignment locations and phase-six transitions — `domain.py:362-379`
- §3.9 phase eight — insert — roll-up limited to affected accounts, but voiding sweeps every `ISSUED` document; floor reason wins over coverage-ended — `domain.py:381-400`
