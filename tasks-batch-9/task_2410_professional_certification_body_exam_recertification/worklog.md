# Worklog — task_2410_professional_certification_body_exam_recertification

## Step 1: Create task directory — 2026-09-02T09:41:38.285Z

Created `tasks/task_2410_professional_certification_body_exam_recertification/` and its `workspace/` subdirectory. Directory name was pre-allocated by the caller (no index scan performed).

## Step 2: Generate Scaffold (partial resume — design indices only) — 2026-09-02T12:38:00.000Z

**Orchestrator resume decision (no user available; reasoning recorded per AUTONOMY clause).** On entry the filesystem held a complete, self-consistent `SCAFFOLD.yaml` (2698 lines; top-level keys scenario, domain_name, api_prefix, complexity_profile, response_envelope, entities, state_machines, concurrency_rules, calculations, validations, priority_conflict_notes, endpoints, errors, roles, rbac_notes — correctly *without* `scaffold_difficulty_design` / `scaffold_corner_design`) from a prior run that crashed before writing the two design-index files. `workspace/` was empty — no INSTRUCTION.md, no PRD.md, no test_suite/, no test_helpers/, no implementation/. Since **nothing downstream had been built against SCAFFOLD.yaml**, regenerating it would have been safe but wasteful and would have discarded a valid 162 KB artifact; I therefore ran Step 2 in partial mode: the subagent was instructed to treat the existing SCAFFOLD.yaml as authoritative and read-only, and to emit only the two missing §1.8/§1.9 indices derived from it. Verified post-hoc that SCAFFOLD.yaml content was not altered by the subagent.

**Orchestrator-applied YAML syntax repair (content-neutral).** The subagent reported SCAFFOLD.yaml did not parse under PyYAML: 40 `input:` flow sequences used bare trailing `?` optional markers (`input: [dry_run?]`, `input: [decision, review_note?]`, and the 5-line `POST /programs` block at lines 1826–1830), and `?` is a reserved indicator in YAML flow context. The subagent worked around it with a quoted copy at `/tmp/t2410/SCAFFOLD.yaml` rather than editing the real file. I repaired the real file in place: 132 bare `token?` occurrences on those 40 lines were wrapped in double quotes (`dry_run?` → `"dry_run?"`). This is purely lexical — no key, value, endpoint, field, or optionality semantic changed; the `?` suffix is preserved inside the string exactly as the generator intended. Pre-repair copy retained at `/tmp/SCAFFOLD.2410.prefix.bak`. All three files now `yaml.safe_load` cleanly. Fixing this before Step 4/5 was necessary because the doc-generator and unit-test-generator both parse SCAFFOLD.yaml as YAML.

**Subagent summary (verbatim):**

Both design indices are complete, YAML-valid, and lint clean. `SCAFFOLD.yaml` was never written (byte-identical modulo the quoting workaround copy — 0 content differences).

**Lint verdict block (verbatim, run with 3 explicit paths because the real SCAFFOLD.yaml does not parse — see defect 1):**

```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           /tmp/t2410/SCAFFOLD.yaml
  Difficulty design:  tasks/task_2410_professional_certification_body_exam_recertification/SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      tasks/task_2410_professional_certification_body_exam_recertification/SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    65
  §1.1 entities declared:     12
  §1.8 instances scanned:     18
  §1.9 instances scanned:     57
  Calls scanned (§1.8+§1.9):  1371

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

## Deliverables

`/home/ubuntu/github/CodingPRD/tasks/task_2410_professional_certification_body_exam_recertification/SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 2483 lines, **18 non-stub instances**, 9 rule_ids × 2: `dual_variant_calc`, `combinatorial_formula`, `non_linear_state_machine`, `transitive_cascade`, `priority_pair_validation_conflict`, `boundary_precision_check`, `cross_entity_state_dependency`, `resource_temporal_overlap`, `compensating_invariant`.

`/home/ubuntu/github/CodingPRD/tasks/task_2410_professional_certification_body_exam_recertification/SCAFFOLD_CORNER_DESIGN.yaml` — 5995 lines, **57 non-stub instances + 14 `excluded_because` stubs** across 8 sections: entities 12, state_machines 15+5, calculations 7+3, validations 9+3, endpoints 7, rbac 3+1, cross_cutting_complexity_layers 3+2, consistency_model 1.

Verified mechanically: 89 instance names unique across both files; every `grounds` entry resolves (error_id, `endpoints.METHOD_/path`, `validations[priority=N]`, entity name); every stub's `difficulty_instance` resolves as `rule_id / name` in §1.8; no empty `setup`/`setup_api_calls`/`trigger`/`assert`; **56/56 §1.6 error_ids referenced** (the guide's Table 6 coverage rule) and 54/65 §1.5 endpoints exercised as real calls (the 11 remaining are read/list GETs observed inside asserts).

## Where SCAFFOLD.yaml was too thin (it was not edited)

1. **Blocking: SCAFFOLD.yaml is not valid YAML.** 40 `input:` flow sequences use trailing `?` optional markers (e.g. `input: [dry_run?]`), which PyYAML rejects, so `scaffold_lint.py <task_dir>` aborts. I linted against a quoted-token copy at `/tmp/t2410/SCAFFOLD.yaml` (only difference is quoting; 0 content-diff lines).
2. `Item.review_round` — §1.1 `default: 1` vs `POST /items` side effect `review_round = 0`. Absolute value unassertable; §1.8 asserts a delta from a captured value.
3. `GET /registry/verify` — says a PUBLISHED-but-EXPIRED credential is disclosed with `credential_status EXPIRED`, but an EXPIRED Certificant's `publication_status` is WITHHELD, which the same block says is reported as `ERR_CERTIFICANT_NOT_FOUND`. The "EXPIRED disclosed" corner is unassertable; the `scheduled_actions` instance asserts the 404 (WITHHELD wins).
4. `validations[priority=28]` — ±120-minute padding on both sides implies a 240-minute threshold, contradicting the prose "a 119-minute gap is rejected while a 121-minute gap is allowed". Only unambiguous points asserted.
5. **No programme-update endpoint**, so the §1.9 `conditional_feature_flags` slot cannot toggle a flag on one programme; it is covered by a cross-programme comparison (explicit `POOLED` vs flag-omitted default `OPERATIONAL_ONLY`), stated in the instance's `distinguishing_aspect`.
6. No admin Certificant creation endpoint — every recertification/discipline corner pays a 24-call exam pipeline in `setup_api_calls`.
7. `RecertificationCycle.starts_on` (and the successor cycle's) is not pinned by any side effect, and reinstate's "grace_ends_on extended by recert_grace_days" does not name the base date (assumed old value + 90 d).
8. `POST /disciplinary-cases/{id}/respond` precondition says `acting X-User-ID == case.certificant_id`, while §1.7 and validation priority 6 use the Certificant's `candidate_id`; recipes use `candidate_id`.
9. With `form_length: 1` the Angoff clamp `ceil_cut = floor(0.90 × 1) = 0` pins `raw_cut_score` to 0 regardless of panel judgement (degenerate but deterministic).
10. **Table 6 (Errors) has no claim-type table in the guide**, so no `section: errors` block is emitted (documented in the file header); error triggerability lives in the validations/endpoints/rbac instances. `ops_run_checkpoint`, one of §1.0.1's active layers, has no row in the guide's complexity-layer table and is covered as `scheduled_actions`.

## Step 3: Copy Shared Files — 2026-09-02T12:38:45.000Z

Copied `INSTRUCTION.md` from the project root to `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-02T13:00:00.000Z

Orchestrator verification before accepting: `workspace/PRD.md` is 492 lines, tail ends on the closing row of the §5 error table (`| `ERR_ITEM_NOT_OPERATIONAL` | 422 |`) — not truncated mid-section. Header naming confirmed: 4 occurrences of `X-User-Role`, 0 of the scaffold's `X-Role`.

**Subagent summary (verbatim):**

PRD generation is complete.

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_2410_professional_certification_body_exam_recertification/workspace/PRD.md` — **492 lines**

**Sections rendered (all present, in order):**
- `# Professional Certification Body API — Product Requirements Document`
- `## 1. Introduction`
- `## 2. Global Specifications & System-Wide Principles` — 2.1 User and Role-Based Access Control; 2.2 API Response Structure (byte-identical verbatim block, both success and error sub-headings); 2.3 Pagination and List Filtering; 2.4 Resource Identity, Timestamps and the Logical Clock; 2.5 Optimistic Concurrency on Parent Records; 2.6 Numeric Precision and Rounding Discipline; 2.7 Request Validation Order and Rejection Precedence (all 47 validation layers plus the 5 priority-conflict notes); 2.8 Nested Path Resolution and Reverse-Reachability Reads; 2.9 Cascade Discipline and Derived-Field Invariants; 2.10 Status Codes and Write Semantics
- `## 3. Business Logic & Workflows` — 3.1 Program Definition/Blueprint/Activation; 3.2 Item Authoring & Peer Review; 3.3 Response Data, Item Statistics & Flagging; 3.4 Item Retirement & Form-Rebuild Cascade; 3.5 Form Assembly, Standard Setting & Publication; 3.6 Eligibility Review, Dimension Verification & Audit Sampling; 3.7 Session Capacity, Registration & Seat Management; 3.8 Check-in, Scoring & Score Release; 3.9 Security Incidents & Score Holds; 3.10 Credential Issuance, Registry Publication & Public Verification; 3.11 Recertification; 3.12 Discipline, Sanction & Revocation; 3.13 The Scheduled Maintenance Run
- `## 4. Endpoint Definitions` — intro paragraph on status codes + 4-column table (Method | Path | Description | Authorized Role(s)), **65 rows**
- `## 5. Error Code Catalogue` — 2-column table (Error ID | HTTP Status Code), **56 rows**

**Final section confirmed complete:** the file's last line is `| ERR_ITEM_NOT_OPERATIONAL | 422 |`, the closing row of the §5 table. No `CONTINUE` markers, no `...`/`…`, no TODO/TBD, and no audit footer remain anywhere in the file.

**Hard Contract results (mechanically verified, reported here only — not written into PRD.md):**
- **Contract 1 — Field-Name Coverage: PASS.** All 180 distinct field names across the 12 entities plus every endpoint `input` / `query_params` / `path_params` / bespoke-response field appear verbatim in backticks. One gap was found and fixed during verification (`cycle_id` on `CEUActivity`, now named in §3.11). Missing set is empty.
- **Contract 2 — Rule Coverage: PASS.** All 72 state-machine transition pairs (after expanding multi-state `from` values and the two `ExamRegistration` dimensions) are expressed in prose; all 56 error identifiers are triggered in §2/§3 prose, not merely tabulated; all enum values of every entity field appear; all 47 validations, 3 concurrency rules, 16 calculations, and all field defaults are rendered operator-free. All 65 scaffold endpoints and all 10 roles are present.
- **Contract 3 — §3 Path Purity: PASS.** Of the 407 distinct backticked tokens between `## 3.` and `## 4.`, zero begin with `/`, zero contain a `/` at all, and zero begin with a bare HTTP method. All URL paths are confined to §2.1/§2.4/§2.5 and the §4 table.

**Withheld-file constraint honored:** neither `SCAFFOLD_DIFFICULTY_DESIGN.yaml` nor `SCAFFOLD_CORNER_DESIGN.yaml` was opened, grepped, or referenced, and no sibling task directory was read. Verification scripts read only `SCAFFOLD.yaml` and `workspace/PRD.md`.

**One authoring note worth relaying:** the scaffold's validation messages spell the role header as `X-Role`, which conflicts with the generator spec's mandated `X-User-Role`; the PRD uses `X-User-Role` throughout, consistent with the skill's contract-level rule and the reference scaffold/PRD pair. Similarly, `review_round`'s initial value follows the entity table (`1`) rather than the conflicting `POST /items` side-effect line (`0`).

## Step 5: Generate Unit Tests — 2026-09-02T16:25:00.000Z

**Orchestrator note — this step ran in two passes because the first subagent died to an infrastructure fault.** Pass 1 (launched ~14:30 UTC) wrote the complete `test_helpers/` (all 9 modules) and `test_suite/conftest.py` + `test_01_*.py` … `test_23_*.py` (115 test functions) and then terminated with `API Error: The system encountered an unexpected error during processing` — no summary was returned, so no pass-1 report exists to paste. The orchestrator recovered by inspecting the filesystem directly: `grep -rh "Design: "` over `test_suite/` showed 115 tags, 115 test functions, and the distinct-instance tally proved queue A complete (18/18 §1.8 instances) and queue B partial (`entities` 12/12, `state_machines` 12/15, all other §1.9 sections 0). Pass 2 was launched as a resume subagent carrying an explicit 33-instance worklist (the exact §1.9 `name:` values still untranslated), instructed to read and reuse the existing `test_helpers/` rather than restructure it, to continue file numbering from `test_24_*.py`, and to emit no further Difficulty-tagged tests. No pass-1 artifact was regenerated or overwritten.

**Pass-2 subagent summary (verbatim):**

The queue-B (Corner) translation is finished. Final report:

## New test files (all under `/home/ubuntu/github/CodingPRD/tasks/task_2410_professional_certification_body_exam_recertification/test_suite/`)

| file | tests | §1.9 instances translated |
|---|---|---|
| `test_24_discipline_and_reexam_state_machines.py` | 7 | state_machines ×2 |
| `test_25_scoring_and_sampling_calculations.py` | 4 | calculations ×2 |
| `test_26_credit_accrual_calculations.py` | 6 | calculations ×3 |
| `test_27_carryover_and_reinstatement_calculations.py` | 5 | calculations ×2 |
| `test_28_eligibility_validations.py` | 8 | validations ×4 |
| `test_29_registration_attempt_validations.py` | 7 | validations ×3 |
| `test_30_candidate_and_registry_endpoints.py` | 5 | endpoints ×2 |
| `test_31_item_review_and_form_assembly_endpoints.py` | 8 | endpoints ×3 |
| `test_32_blueprint_and_strict_window_validations.py` | 5 | validations ×2 |
| `test_33_maintenance_run_and_cycle_close_endpoints.py` | 6 | endpoints ×2 |
| `test_34_role_and_ownership_gates.py` | 7 | rbac ×3 |
| `test_35_cross_cutting_layers.py` | 6 | cross_cutting ×3 |
| `test_36_synchronous_consistency.py` | 3 | consistency_model ×1 |

**77 new tests, 33 instances.** Suite total: 36 files, **192 test functions**.

## Coverage tally (full suite)

- Queue A (Difficulty, §1.8): **18/18** distinct tags — untouched, no new Difficulty-tagged tests emitted.
- Queue B (Corner, §1.9): **56 of 57** non-stub instances, one deliberate skip. Per section: entities 12/12, state_machines 14/15, calculations 7/7, validations 9/9, endpoints 7/7, rbac 3/3, cross_cutting_complexity_layers 3/3, consistency_model 1/1. All 4 `excluded_because` stubs ignored as instructed.

## Skipped instance (PRD-first filter)

`Corner/state_machines/minor_security_incident_places_no_score_hold_and_scoring_continues` — fails condition 2 (PRD does not uniquely derive the asserted outcome; it derives the opposite). PRD §3.9 makes the substantiation cascade unconditional — "**Hop one**, which always runs: the registration's `score_status` moves to `VOIDED` and both `scaled_score` and `outcome` are cleared to null" — and "The mere existence of an `OPEN` incident on a registration is enough to block score release with `ERR_SCORE_UNDER_SECURITY_HOLD`, whatever its severity", while the instance asserts `score_status == SCORED`, `scaled_score == 800`, `outcome == PASS` and a 200 on report-score after SUBSTANTIATE. Its `incident_type: LATE_ARRIVAL` is also outside the PRD's incident-type enum. No placeholder, no weakened variant emitted.

Two sub-asserts inside otherwise-translatable instances were dropped for the same PRD-wins reason: the maintenance-run instance's `ExamSession.status == OPEN` at a clock past `starts_at` (PRD §3.7 makes it `CLOSED`; the test asserts `seats_reserved == 0` instead), and the stats-eligibility instance's `stat_basis_applied == null` on a fresh DRAFT item (PRD §3.2 pins it to `INSUFFICIENT_DATA`, which is what the test asserts).

## `test_helpers/` changes

**None.** Everything needed already existed. The one gap — a role header with no `X-User-ID`, which `build_user_headers` cannot express — is a module-local constant `ROLE_WITHOUT_AN_IDENTITY` in `test_34`, and the headerless public read uses `api.verify_registry(params)` with `headers` omitted.

## Self-check output

- `python3 -m py_compile test_suite/test_*.py test_suite/conftest.py test_helpers/*.py` → **COMPILE_OK_ALL** (`__pycache__` removed afterwards).
- `grep -rn "X-Role\|pytest.mark.skip\|pytest.mark.xfail" test_suite/ test_helpers/` → **NONE**.
- Design-tag audit: 74 distinct tags over 192 tests; **untagged: 0, dual-tagged: 0, tags pointing at non-existent instances: 0**; `MISSING` = the single deliberate skip above.
- Static attribute audit of every `fx.*`, `f.*`, `ax.*` and `api.*` reference in `test_24`–`test_36` against the helper modules and `ApiClient` → **no missing attributes**.

## Step 6 isolation measure (orchestrator, pre-Step-6) — 2026-09-02T16:26:00.000Z

The skill obtains Step 6's isolation from `test_suite/` by launching Steps 5 and 6 concurrently, so that the directory does not exist when the implementation generator starts. That ordering guarantee was unavailable here: Step 5 had to run alone (and twice), so `test_suite/` and `test_helpers/` were already on disk before Step 6 could start. To restore *physical* isolation rather than relying only on a prompt-level prohibition, the orchestrator quarantined both directories for the duration of Step 6:

    mv test_suite      .step5_quarantine/test_suite
    mv test_helpers    .step5_quarantine/test_helpers

**RECOVERY NOTE for any future resume of this task: if `test_suite/` or `test_helpers/` appear to be missing from the task root, look in `.step5_quarantine/` and `mv` them back BEFORE concluding Step 5 needs to run — the 192 generated tests are intact in there.** The orchestrator restores them itself immediately after Step 6's subagent exits and before Step 7's first sweep.

## Step 6: Generate Implementation — 2026-09-02T17:08:00.000Z

**Orchestrator note.** Ran alone rather than concurrently with Step 5 (Step 5 had already finished, in two passes — see above), with isolation supplied instead by the `.step5_quarantine/` move recorded in the previous entry plus an explicit prompt-level prohibition on reading the quarantine directory, either design index, or any sibling task. Immediately after the subagent exited, the orchestrator restored both directories to the task root and removed the now-empty `.step5_quarantine/`; verified present afterwards: `test_suite/` with 36 `test_*.py` files, `test_helpers/` with 9 modules. Also confirmed no stale `workspace/implementation/results.*.json` existed before Step 7's first sweep.

**Subagent summary (verbatim):**

Implementation complete and verified.

## Module layout (`.../task_2410_.../workspace/implementation/`, 4,305 lines of Python)

| File | Lines | Role |
|---|---|---|
`app.py` | 83 | Flask app, blueprint registration, HTTPException/Exception → error envelope, `0.0.0.0:$PORT`
`db.py` | 102 | `Store`: one `RLock`, the logical clock (`2026-08-01T00:00:00Z` default per §2.4), 12 plain dicts, `new_record`/`touch`/`mark_created`/`ordered`
`dispatch.py` | 24 | `@api`: takes the single process lock once per request, resets `g._touched_ids`, translates `ApiError`
`errors.py` | 72 | all 56 error ids → (status, message)
`middleware.py` | 257 | `X-User-ID`/`X-User-Role`, 10 roles, layers 1–2, body peek + all layer-7 validators
`response.py` | 130 | envelope, `req_` id, pagination (10/1/100), filters
`serialize.py` | 302 | all 12 entity projections
`util.py` | 109 | ISO-8601 ±3-digit stamps, date math, Decimal/ROUND_HALF_UP helpers
`services/calc.py` | 271 | all 16 calculations + pinned constants
`services/derive.py` | 252 | derived-field re-derivation, cycle credit reconciliation
`services/cascades.py` | 217 | item-retirement, incident, mint/close, revocation, elect-reexam cascades
`services/lookup.py` | 85 | layer 3/4 existence → the matching 404
`services/maintenance.py` | 137 | the four-step §3.13 run (commit and dry-run)
`routes/programs.py` | 244 | 6 endpoints
`routes/items.py` | 253 | 7
`routes/forms.py` | 224 | 6
`routes/candidates.py` | 69 | 3
`routes/applications.py` | 193 | 5
`routes/sessions.py` | 126 | 3
`routes/registrations.py` | 367 | 8
`routes/incidents.py` | 115 | 4
`routes/certificants.py` | 110 | 5 (incl. header-free `GET /registry/verify`)
`routes/cycles.py` | 210 | 7
`routes/ceu.py` | 123 | 3
`routes/discipline.py` | 188 | 6
`routes/ops.py` | 42 | 2

Plus `start.sh` (guarded pip, `exec python3 app.py`, foreground, `$PORT`, `0.0.0.0`) and `requirements.txt`.

## Endpoint count: 65 — exact
Dumped from `app.url_map` and matched one-for-one against the PRD §4 table (no extras, no omissions). No stubs: `grep` for `TODO|FIXME|NotImplemented|bare pass` returns nothing; an AST pass shows no unused imports.

## Validation ordering
All 47 layers are implemented in the §2.7 ascending order, with the ladder treated as normative wherever §3 prose enumerates checks in a different sequence. Each layer's error id is raised from at least one route (verified by grep across all 44 non-404 ids plus the 12 `*_NOT_FOUND` ids in `lookup.py`). The error catalogue is an exact 56/56/56 match between `errors.py`, SCAFFOLD, and the ids the PRD names.

Deliberate precedence decisions where the two texts disagreed (ladder wins in every case):
- registration create: 31 → 32 (retake wait) → 38 (attempt ceiling) → 44
- seat claim: 14 → 20 → 28 (candidate window) → 29 (session closed) → 46
- cycle close: 11 → 16 (certificant active) → 39 (credits)
- CEU review: 12 (cycle state, then activity state) → 16
- audit-verify: 12 → 19 (SoD)
- decide: 12 → 17 → 19 → 40, with §3.12's SANCTIONED-requires-ACTIVE guard last (layer 16's "applies to" list excludes deciding)
- registration is accepted against an `ACTIVE` **or** `SUPERSEDED` program, per §3.1's verbatim "remain usable for registration"

## Storage constraints
In-memory only: 12 `dict`s inside a single `Store` instance. No SQLite, no file writes, no `/tmp`, no env-backed persistence, and zero records created at import time — every entity in both smoke runs came from a client call. Concurrency: exactly one `threading.RLock`, acquired once at the `@api` boundary; no handler acquires a second lock, so deadlock is structurally impossible. `app.run(threaded=True, use_reloader=False)`.

## Boot smoke test
`PORT=18410 bash start.sh` booted in <4s and answered. Two scripted passes exercised **every resource family and all 65 route handlers' families**, all green:

- Pass 1 (~90 probes): program → item authoring/peer review/pretest→OPERATIONAL → form assembly/panel rating/cut score (`raw_cut_score=1`, stale-version 412) → publish → candidate → application (two-dimension verify → APPROVED) → session (room double-booking 409) → registration → schedule/cancel/re-schedule → clock → check-in → CRITICAL-free incident → submit-responses (`scaled_score=800 PASS`) → report-score blocked by OPEN incident 409 → adjudicate → report-score → certificant minted `CWP-2026-00001` → `GET /registry/verify` with **no headers** 200, unknown 404 → CEU claim (403 for a foreign holder) → SELECT_FOR_AUDIT → audit-verify SoD 409 → verify by a second reviewer → cycle SATISFIED 1.0/1.0 → close → successor cycle 2 → elect-reexam → reinstate on a non-LAPSED cycle 409 → disciplinary case (due-process 422, wrong respondent 403) → SANCTIONED → registry suppressed 404 → dry run → commit run reactivated the holder → second case → revoke-by-opener 409 → REVOKED by a second officer → `REMOVED`, `current_cycle_id` cleared → 401/403/400 probes.
- Pass 2 (~80 probes): proctor-pool ceiling (50 committed + 1 overlapping → 409; adjacent window → 201; wrong-modality `center_code` → 400), buffered candidate-window conflict 409, no-show sweep (seat NO_SHOW, attempt consumed, next registration 422), lapse sweep (fee `25755` = 25000 + 250 + 2%), underpaid reinstatement 402 then reinstatement → cycle OPEN / holder ACTIVE+PUBLISHED, elect-reexam then a passing re-exam satisfying the existing cycle **without minting a second certificant**, close, CRITICAL incident → WITHHELD → VOIDED + candidate BARRED for 730 days → barred registration 409 → unbar sweep, item retirement cascade (form NEEDS_REBUILD, seat released with `form_reassignment_required`, `seats_reserved` recounted).

No endpoint failed to work. Both servers were killed; ports 18410/18411 are free. Two pre-existing defects found and fixed during this pass: the clock default was `2025-01-01` instead of §2.4's `2026-08-01T00:00:00Z`, and an out-of-contract `GET /security-incidents` collection route was removed.

## Step 7: Run Tests and Iterate — 2026-09-02T17:36:00.000Z

**Orchestrator independent verification (not taken on the subagent's word).** Read all 8 `workspace/implementation/results.{1..8}.json` directly: every round reports `passed=192 total=192 failed=0 errors=0`. Also grepped `test_suite/` and `test_helpers/` for `pytest.mark.skip`, `pytest.mark.xfail`, and `X-Role` — zero hits, so the green sweep was not bought with skips, xfails, or a reverted header contract.

**Subagent summary (verbatim):**

Suite is green. Final report:

## Summary

**Iterations run: 2.** Iteration 1 exposed 5 failures, identical in all 8 rounds (fully deterministic — no flakiness, no load-induced timeouts, no reaped sweeps). Iteration 2 after fixes: **8/8 rounds at 192/192 passed, 0 failed, 0 errors**, ~339s per round.

**Tests deleted: none.** Every failing test's rule was verbatim-covered by PRD and uniquely derivable; all 5 failures were test-artifact bugs (STEP 2), not PRD-silence.

**Fixes applied to `test_helpers/`: none.** The fixture/factory/header layer was already PRD-faithful (notably `make_certificant_headers` correctly keys on `Candidate.id`, and `api_errors.py` already carried the correct 422 for `ERR_BLUEPRINT_DEFICIENT`).

**Fixes applied to `implementation/`: none.** The implementation was correct on all 5 counts; no PRD-required check was weakened or removed.

**Fixes applied to `test_suite/`** (all four make the test more faithful to PRD; no assertion was weakened and no exact `error_id` check was downgraded):

- `test_suite/test_12_publication_blueprint_gate.py` — `test_publication_is_refused_while_the_blueprint_is_deficient` and `test_the_identical_publish_call_succeeds_once_the_posture_returns` asserted HTTP **409** for `ERR_BLUEPRINT_DEFICIENT`. PRD §5's catalogue and §2.7 layer 34 both pin it to **422**; the suite's own `test_helpers/api_errors.py` map already said 422. Corrected both to 422.

- `test_suite/test_06_score_hold_and_release.py` — `test_release_is_blocked_while_the_incident_is_open` raised a **CRITICAL** incident, which by PRD §3.9 freezes `score_status` to `WITHHELD`. The subsequent report-score therefore violated *two* layers at once, and §2.7's normative ladder resolves that to layer 12 `ERR_INVALID_STATE`, never the layer-21 error the test asserted — the setup made the asserted rule unobservable. Switched the setup to a **MAJOR** incident (places no hold, so `score_status` stays `SCORED`), which isolates layer 21 exactly as PRD §3.9's "whatever its severity" states, keeping the exact `ERR_SCORE_UNDER_SECURITY_HOLD` assertion intact. This was the suite's only coverage of that error id, so relaxing rather than re-targeting it would have lost the layer entirely.

- `test_suite/test_02_ceu_accrual_basis.py` — `test_each_first_cycle_pins_its_own_programme_basis_and_window` built two full `pipeline_through_certificant` chains back to back. The first leaves the logical clock parked at its session's `starts_at`, so the second chain's seat claim was correctly refused with `ERR_SESSION_CLOSED` (PRD §3.7 layer 29: a session whose `starts_at` has been reached admits no new claims). Added `fx.reset_clock(api)` between the two chains, which also preserves the test's requirement that both cycles open on 2026-08-10.

- `test_suite/test_18_program_entity_corners.py` — `test_retrieval_after_activation_returns_the_stored_row_with_inputs_intact` asserted `updated_at != created_at` after activation, but both stamps come from the logical clock, which had not moved (PRD §1's determinism commitment — "any two replays of the same request sequence produce byte-identical records" — requires exactly that). Rather than drop the assertion, advanced the clock to `2026-08-02` between creation and activation, which makes PRD §2.4's "refreshed on every mutation" observable under either the logical-clock or wall-time reading, preserving the coverage.

**Note for the generators:** no Zero-Silence or unique-derivability violations to report — the four defects were mistranslations and setup-ordering bugs in `test_suite/`, all repairable in place.

## Step 8 skip-condition adjudication (orchestrator) — 2026-09-02T17:37:00.000Z

Not skipped. The skill skips Step 8 only when Step 7 exited on its FIRST sweep with 0 deletions AND 0 `test_suite/` fixes AND 0 `test_helpers/` fixes AND 0 `implementation/` fixes. Step 7 ran 2 iterations and applied 4 `test_suite/` fixes, so the condition fails on two counts even though `implementation/` fixes were 0. Step 8 therefore runs, with `<step_7_diff>` = the four `test_suite/` repairs above; each is a site where the PRD did not pin a behavior tightly enough for the test generator to translate it correctly on the first pass (status code for `ERR_BLUEPRINT_DEFICIENT`, severity-vs-hold interaction, clock advancement semantics), which is exactly the class of PRD gap Step 8 exists to close.

## Step 8: Finalize PRD — 2026-09-02T17:42:00.000Z

**Orchestrator verification.** `diff PRD.md PRD_FINALIZED.md` shows exactly one changed line (492 → 492), the §2.4 common-properties sentence, and the inserted clause describes only clock-sourced timestamp behavior — no new sections, no invented endpoints, no behavior claims beyond the clock. Consistent with the subagent's report of 1 edit and 3 no-edit adjudications.

**Subagent summary (verbatim):**

Done. One edit, one line.

## Counts
- `PRD.md`: 492 lines — `PRD_FINALIZED.md`: 492 lines — **0.0% line delta** (1 line revised in place = 0.20% of lines touched; +468 characters).

## Change
- **§2.4 (Resource Identity, Timestamps and the Logical Clock)** — *revise* — added, inside the existing common-properties sentence, that `created_at` and `updated_at` are read from the logical clock rather than wall time, that a mutation applied while the clock has not moved since creation refreshes `updated_at` to a value identical to `created_at`, and that only an intervening `POST /_clock/set_current_utc` can make the two differ — `implementation/db.py:59` (`new_record`: `stamp = DB.now()` for both stamps), `implementation/db.py:88,91` (`touch`: `updated_at = DB.now()`), `implementation/routes/ops.py:32` (sole assignment of `DB.clock`).

## Pre-edit search log
**(a) Subject:** the source of the `created_at` / `updated_at` stamps, and every other producer of a timestamp the server emits.
**(b) Paths enumerated (grepped `created_at"]\s*=`, `updated_at"]\s*=`, `datetime.now`, `utcnow`, `DB.now()`, `DB.clock`, `.clock =` across all of `implementation/`, then read the hits):** `db.py:57-68` `new_record` (both stamps from `DB.now()`); `db.py:79-92` `touch` (refreshes `updated_at` from `DB.now()` on every mutation, including the second touch of a record inside one request); `db.py:50-51` `Store.now`; `db.py:22,31` clock default `2026-08-01T00:00:00Z`; `routes/ops.py:26-33` the only writer of `DB.clock`; `response.py:24-28` `_base_meta` — the **only** wall-clock read in the codebase, feeding `api_request_timestamp`; `serialize.py:15-16` (both stamps rendered via `fmt_ts`); and every other clock-derived field, all already pinned by PRD prose: `routes/items.py:223,249` `retired_at`, `routes/forms.py:153` `submitted_at`, `routes/applications.py:35,137` `eligibility_expires_on` / recency year, `routes/certificants.py:87` `verified_at`, `routes/discipline.py:176,182` `decided_on` / `suspension_until`, `services/cascades.py:71,121` `barred_until` / `issued_on`, `services/maintenance.py:22,33,40,49,60,67,113`. Also confirmed `routes/programs.py:206,215` (the Step 7 site — activation `touch`es the program and any superseded sibling) goes through `db.touch` and no other stamping path.
**(c) Wording adjustment:** scoped the new sentence explicitly to "Both of those two stamps" instead of a general "timestamps in this system", because `response.py:27` reads wall time for the envelope's `api_request_timestamp`; a universal claim would have mis-described that path. Also phrased the equality consequence as "refreshes `updated_at` to a value identical to `created_at`" rather than "leaves `updated_at` untouched", to stay consistent with `db.py:88` which *does* rewrite the field on a repeat touch within one request, and kept the clock-mover clause tied to the endpoint name after confirming `DB.clock` is assigned nowhere else.

## Items deliberately left unedited (already uniquely pinned)
- **(a) HTTP status of `ERR_BLUEPRINT_DEFICIENT` / §3-vs-§5 governance.** No edit. §2.7 layer 34 and the §5 catalogue both say **422**, and `errors.py:47` agrees. I machine-diffed all 56 catalogue entries against `errors.py` and against every inline `ERR_X (HTTP n)` / `ERR_X (n)` mention in §2–§3: **zero disagreements anywhere in the document**, so there is no §3-vs-§5 conflict to arbitrate and nothing for a tie-break rule to do. This failure was purely the test's mistranslation.
- **(b) Incident severity vs. score hold, and the two-layer collision.** No edit. §3.9 already pins that an `OPEN` incident of *any* severity blocks release (`registrations.py:347-350`) while only `CRITICAL` freezes `score_status` to `WITHHELD`, and only from `PENDING`/`SCORED` (`incidents.py:55-59`). The collision resolution is already forced: §3.8's "score must currently be `SCORED`, or `ERR_INVALID_STATE`" is layer 12 and the hold is layer 21, matching `registrations.py:344-350`. (Note the deliberate asymmetry the PRD also already states: `submit-responses` at `registrations.py:303-308` admits `WITHHELD` past layer 12 specifically so it can answer `ERR_SCORE_UNDER_SECURITY_HOLD`.)
- **(d) Session-closed seat-claim gate.** No edit. §2.7 layer 29 plus §3.7 ("the logical clock must be strictly before its `starts_at`") exactly match `registrations.py:211` (`DB.now() >= starts_at`), the cancel path at `registrations.py:242`, and the derived `CLOSED` status at `services/derive.py:136`. The test failure came from a fixture leaving the clock parked at `starts_at`, not from PRD silence.

## Step 9: Complete PRD — 2026-09-02T18:00:00.000Z

**Orchestrator verification.** `workspace/PRD_COMPLETED.md` exists, is 492 lines, and ends on the closing row of the §5 error catalogue — complete, not truncated. Confirmed `test_suite/` (36 `test_*.py`) and `test_helpers/` (9 modules) are still intact at the task root despite the subagent's note below: it looked for them under `workspace/`, but they live at the task root, so that note is a path slip on its part and not a missing-artifact problem — and Step 9 designates tests non-authoritative anyway, so the alignment was correctly driven from `implementation/`. Also verified by mtime that nothing was edited after the green sweep: newest implementation file 17:03:29, newest test file 17:27:01, newest `results.*.json` 17:32:53 — the 8/8 × 192/192 result still describes the code as it stands, and Steps 8–9 touched only PRD documents.

**Subagent summary (verbatim):**

`PRD_COMPLETED.md` is complete. All 24 implementation modules were walked; every divergence found is now pinned inline.

## Counts

- **Source vs completed:** `PRD_FINALIZED.md` 492 lines / 110,607 chars → `PRD_COMPLETED.md` 492 lines / 117,307 chars. **Char delta +6,700** (+6.1%); line count unchanged (25 paragraphs revised in place, no sections added, no paragraphs added).
- **Ambiguity-pins: 23. Mismatch-revisions: 7.** (30 changes total.)

## Changes

- §2.2 — insert — ambiguity — `api_request_timestamp` is read from wall-clock time, not the logical clock — `implementation/response.py:27`
- §2.3 — insert — ambiguity — limit out of range / negative offset / non-integer either param is malformed; offset has no upper bound and an over-the-end offset yields an empty page — `implementation/response.py:76`
- §2.3 — insert — ambiguity — records sharing a `created_at` (the normal case, since the clock only moves explicitly) are ordered among themselves by creation sequence — `implementation/db.py:100`
- §2.3 — insert — ambiguity — filters match verbatim (bool as `true`/`false`, int as decimal text); a non-matching or unrecognised enum value yields an empty page; only `counted` can itself be malformed; unknown query params are ignored — `implementation/response.py:95,107`
- §2.4 — insert — ambiguity — `version` advances by exactly one per record per request however many hops rewrite it, and a record created by the request stays at 1 — `implementation/db.py:79`
- §2.4 — insert — ambiguity — `set_current_utc` echoes `current_utc` back exactly as written, unrenormalised; supplied timestamps accept bare `YYYY-MM-DD` (midnight UTC), offsets (converted), and zone-less values (taken as UTC) — `implementation/routes/ops.py:28`, `implementation/util.py:28`
- §2.7 layer 4 — insert — ambiguity — seat claiming is body-reference-guarded too; absent/null/non-string reference is a collection 404; fixed per-operation resolution order — `implementation/services/lookup.py:22-66`
- §2.7 layer 13 — **revise** — **mismatch** — the layer covers application submission and form publication; registration creation admits `ACTIVE` **or** `SUPERSEDED` and only `DRAFT` refuses — `implementation/routes/registrations.py:58`
- §2.8 — revise — **mismatch** — the malformed-filter claim narrowed to pagination parameters and boolean filter values only — `implementation/response.py:76,95`
- §2.9 — insert — ambiguity — a no-op re-derivation leaves program/form/cycle wholly untouched (no `updated_at`, no `version`), while a cascade-recounted session is always stamped — `implementation/services/derive.py:80,143`
- §3.1 — insert — ambiguity — `credential_code` is 2–12 chars, each an uppercase letter or digit, else `ERR_INVALID_REQUEST` — `implementation/routes/programs.py:100`
- §3.3 — insert — ambiguity — all seven batch fields required, six counts non-negative integers, no relationship among the counts validated — `implementation/routes/items.py:188`
- §3.3 — insert — ambiguity — an `APPROVED` item ingesting a non-pretest batch stays `APPROVED`; there is no direct `APPROVED → OPERATIONAL` path — `implementation/routes/items.py:188`
- §3.3 — insert — ambiguity — the two status moves chain inside a single ingest call — `implementation/routes/items.py:188`
- §3.5 — **revise** — **mismatch** — `form_code` is recorded as given with no uniqueness enforced against sibling forms — `implementation/routes/forms.py:36`
- §3.5 — insert — ambiguity — panel ratings accepted only while the form is `ASSEMBLED` or `CUT_SCORE_SET` (else `ERR_INVALID_STATE`); the rate is non-negative with no upper bound — `implementation/routes/forms.py:131`
- §3.5 — insert — ambiguity — a completing rating sets `RATINGS_COMPLETE` even when it overwrites a prior `ADOPTED` — `implementation/routes/forms.py:131`
- §3.7 — **revise** — **mismatch** — seat-claim preconditions reordered to the ladder order actually enforced: state → form `PUBLISHED` → candidate `ACTIVE` → window collision → session closed → seats — `implementation/routes/registrations.py:185-216`
- §3.8 — **revise** — **mismatch** — check-in preconditions reordered: state → form `PUBLISHED` → candidate `ACTIVE` → check-in window — `implementation/routes/registrations.py:256-282`
- §3.10 — insert — ambiguity — the first cycle's `starts_on` equals the certificant's `issued_on` — `implementation/services/cascades.py:139`
- §3.10 — insert — ambiguity — `certificate_number` is supplied as a query parameter of that name — `implementation/routes/certificants.py:59`
- §3.10 — revise — ambiguity — `ERR_INVALID_REQUEST` covers only absent/empty/whitespace-only; any other value matches verbatim, so stray whitespace gives `ERR_CERTIFICANT_NOT_FOUND` — `implementation/routes/certificants.py:60-70`
- §3.11 — insert — ambiguity — a credit claim requires the cycle to be `OPEN` **or** `SATISFIED` (else `ERR_INVALID_STATE`); a satisfied cycle still accepts claims — `implementation/routes/cycles.py:167`
- §3.11 — insert — ambiguity — the chronological cap fill breaks remaining ties by creation order — `implementation/services/calc.py:194-197`
- §3.11 — insert — ambiguity — cycle-status re-derivation reaches only cycles currently `OPEN`/`SATISFIED`; `LAPSED`/`CLOSED`/`VOID` are never re-derived — `implementation/services/derive.py:236-252`
- §3.11 — **revise** — **mismatch** — elect-reexam leaves `status` as found (a `LAPSED` cycle stays `LAPSED` with its fee intact); `election_note` is validated but not retained; an activity already at false/0.00 is not re-stamped — `implementation/services/cascades.py:206-217`, `implementation/routes/cycles.py:104`
- §3.11 — insert — ambiguity — reexam satisfaction is candidate-scoped irrespective of program, picks the lowest `cycle_number`, and leaves the holder's own `status` untouched — `implementation/routes/registrations.py:355-363`
- §3.12 — **revise** — **mismatch** — decide-case check order corrected: state → already-revoked → segregation of duties → due-process round → the sanction branch's `ACTIVE` demand (so a suspended respondent with 0 rounds reports `ERR_DUE_PROCESS_INCOMPLETE`) — `implementation/routes/discipline.py:152-172`
- §3.13 — insert — ambiguity — step one's comparison is strictly past `ends_at`, and the owning application is re-stamped (`updated_at`, `version`) because its derived `attempts_consumed` changed — `implementation/services/maintenance.py:14-24,84-89`
- §3.13 — insert — ambiguity — step two's comparison is strictly past `eligibility_expires_on` — `implementation/services/maintenance.py:27-35`

## Notes

- `test_helpers/` and `test_suite/` do not exist in this workspace, so the auxiliary cross-reference was unavailable; alignment was driven entirely from `implementation/`, which the brief designates as the authority.
- Already-adjudicated items were left alone: header pair, `GET /registry/verify` as the sole header-free endpoint, `review_round` starting at 1, respond-endpoint identity check, the 56-entry §5 catalogue, and §2.4's clock-sourced `created_at`/`updated_at`.

## Pipeline complete — 2026-09-02T18:01:00.000Z

All nine steps are done for `task_2410_professional_certification_body_exam_recertification`. Final artifact inventory at the task root: `SCAFFOLD.yaml` (2698 lines), `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (2483), `SCAFFOLD_CORNER_DESIGN.yaml` (5995), `test_helpers/` (9 modules), `test_suite/` (36 files / 192 tests), `worklog.md`; under `workspace/`: `INSTRUCTION.md`, `PRD.md`, `PRD_FINALIZED.md`, `PRD_COMPLETED.md` (492 lines each), `implementation/` (24 modules / ~4,300 lines / 65 endpoints / `start.sh`) with `results.{1..8}.json` from the final all-green sweep, and `sweep.log`. Test outcome of record: 8 concurrent rounds under `--isolation per-test-server`, each 192/192 passed, 0 failed, 0 errors. Zero tests deleted across the whole pipeline; zero `implementation/` fixes were needed in Step 7.
