# Worklog — task_2713_trauma_center_verification_registry_reporting

## Step 1: Create task directory — 2026-09-04T10:34:00.000Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2713_trauma_center_verification_registry_reporting` and its `workspace/` subdirectory. Index 2713 was pre-assigned by the invoking pipeline; no scan of `./tasks/` was performed and no index was auto-allocated (32 pipelines run concurrently on this host, so auto-allocation would collide).

## Step 2: Generate scaffold (subagent) — 2026-09-04T11:58:00.000Z

Done. All three artifacts are written and the scaffold linter reports a clean verdict.

## Files

| File | Lines |
|---|---|
| `/home/ubuntu/github/CodingPRD/tasks/task_2713_trauma_center_verification_registry_reporting/SCAFFOLD.yaml` | 2405 |
| `/home/ubuntu/github/CodingPRD/tasks/task_2713_trauma_center_verification_registry_reporting/SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 1543 |
| `/home/ubuntu/github/CodingPRD/tasks/task_2713_trauma_center_verification_registry_reporting/SCAFFOLD_CORNER_DESIGN.yaml` | 2236 |

## SCAFFOLD.yaml (§1.0–§1.7)
`compliance_audit` / `posture_driven_gating`, graph topology, cyclic state machines, `segregation_of_duties` role model, `difficulty_level: expert_plus`.
- 13 entities, 8 state machines, 2 §1.2.1 concurrency rules (`abstraction-create-stale-case` → `ERR_STALE_CASE_VERSION`, `remediation-submit-stale-cycle` → `ERR_STALE_CYCLE_VERSION`, both 412)
- 9 calculations (2 dual-variant: `verification_readiness_score`, `under_over_triage_rates`), 37 priority-ordered validations, 56 endpoints, 37 errors, 7 roles
- Neither `scaffold_difficulty_design` nor `scaffold_corner_design` key is present

## SCAFFOLD_DIFFICULTY_DESIGN.yaml (§1.8)
24 instances over all 9 required rule ids (>=2 each): dual_variant_calc 2, combinatorial_formula 3, non_linear_state_machine 3, transitive_cascade 2, priority_pair_validation_conflict 3, boundary_precision_check 3, cross_entity_state_dependency 3, resource_temporal_overlap 2, compensating_invariant 3.

## SCAFFOLD_CORNER_DESIGN.yaml (§1.9)
70 instances — 45 with full `test_recipe`, 25 `excluded_because` stubs, spread over all nine taxonomy sections: entities 12, state_machines 16, calculations 8, validations 9, endpoints 4, errors 10, rbac 5, complexity_layers 5, consistency_model 1.

## Verification
- `scaffold_lint.py`: **VERDICT: clean lint** — 481 calls scanned across §1.8+§1.9, all conform to §1.5, and all §1.1 FKs have reverse-reachability.
- Audited independently: 94 instance names globally unique (0 duplicates); every stub's `difficulty_instance` resolves to a real §1.8 instance name; all 37 error ids appear in at least one design instance.
- One self-consistency fix during the lint loop: §1.5 `POST /registry-cases` listed `ed_disposition` as required while §1.1 declares `default: ADMIT` for it — changed to `"ed_disposition?"`. (Earlier in the run, five §1.6 `triggered_by` texts were also corrected to match their §1.4 rules' actual scope.)
- No sibling task directory was read, listed, globbed, or grepped at any point.

## Step 3: Copy shared files (bash) — 2026-09-04T11:58:30.000Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` to `workspace/INSTRUCTION.md`.

## Step 4: Generate PRD (subagent) — 2026-09-04T12:13:00.000Z

PRD generation is complete and verified.

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_2713_trauma_center_verification_registry_reporting/workspace/PRD.md`

**Final line count: 470.** Verbatim last 3 lines:

```
| `ERR_AGREEMENT_INTERVAL_OVERLAP` | 409 Conflict |
| `ERR_SURVEYOR_WINDOW_CONFLICT` | 409 Conflict |
| `ERR_READINESS_BELOW_THRESHOLD` | 409 Conflict |
```

The file terminates at a real section boundary — the final row of the §5 Error Code Catalogue table, not mid-sentence. Written via 12 chunked `cat >>` heredoc appends; no single Write call, so no 64k truncation risk.

**Hard Contract 1 — Field-Name Coverage: PASS**
- Entity fields: 123 required, 0 missing
- Request-body inputs: 75 required, 0 missing
- Query parameters: 48 required, 0 missing
- (Extraction fixed mid-run: the first scan produced false negatives because fenced JSON blocks in §2.2 desynchronised inline-backtick pairing. Stripping fenced blocks before token extraction gave the clean result above.)

**Hard Contract 2 — Rule Coverage: PASS**
- All 37 `error_id`s from the scaffold appear in §1–§4 prose with their trigger conditions, not only in the §5 table.
- All 37 validations are stated, and the full priority ladder 1->70 is transcribed in §2.11 as Bands A–G, including the three counter-intuitive orderings (posture gate before state check; dictionary CRITICAL abort before penalty application; segregation-of-duties after state validity).
- All 9 calculations transcribed in prose with pinned evaluation order and no pseudocode: `case_inclusion_classification`, `under_over_triage_rates` (both PROVISIONAL_MONITORING and VERIFICATION_AUDIT variants), `dictionary_penalty_scan` (band from score at request start, ascending severity_rank/field_name order, weights 4/2/1, round_half_up, floor at 0.00), `outreach_credit_hour_ledger` (quantize-each-then-sum, contrasted against the wrong sum-then-quantize result), `verification_readiness_score` (both REVIEWER_ASSESSMENT and SELF_ASSESSMENT variants with all four penalty caps), `response_time_compliance`, `readiness_posture` (first-match ladder, gates only case-lock and cycle-submit), `surveyor_window_conflict` (symmetric 24h buffer, cross-cycle candidate set, first conflict by window_start then created_at), `agreement_interval_overlap` (half-open interval, adjacency legal).
- Both `concurrency_rules` documented in §2.9 with their explicit write endpoints, version fields, and 412 error IDs.
- Both 4-hop cascades (CONTINGENCY and UNDER_TRIAGE) transcribed hop-by-hop with counter conservation.
- Only scan flag was `TERMINATED` existing solely inside the compound token `` `ACTIVE -> TERMINATED` ``; fixed by an edit in §3.6 making it a standalone backticked value. Numeric band multipliers 1.0/1.5/2.0 were flagged by the enum heuristic but are correctly plain numbers, not identifiers — no change needed.

**Hard Contract 3 — §3 Path Purity: PASS**
- 817 inline-code tokens scanned across §3.1–§3.9: 0 leading-slash paths, 0 bare HTTP methods, 0 method+path pairs. §3 uses state-transition, role+gerund, and capability framing throughout.

**Structural conformance:** endpoint table 56 rows / exactly 4 columns; error table 37 rows / exactly 2 columns; §2.2 pasted byte-identically from `section-2.2-response-structure.md`; 20 `###` subsections (11 in §2, 9 in §3) with a domain-derived skeleton rather than the example PRD's shape.

**Constraints honoured:** `SCAFFOLD_DIFFICULTY_DESIGN.yaml` and `SCAFFOLD_CORNER_DESIGN.yaml` were never opened, grepped, or referenced; no sibling task directory under `/home/ubuntu/github/CodingPRD/tasks/` was read. The only inputs were `SCAFFOLD.yaml` and the three skill files.

**Orchestrator truncation check (independent):** confirmed 470 lines, headings §1–§5 all present with 20 `###` subsections, and the file ends on the complete 37-row §5 error table — no truncation, no regeneration needed.

## Step 6: Generate implementation (subagent) — 2026-09-04T12:45:00.000Z

Implementation complete and smoke-tested.

## Module list (line counts)

| File | Lines |
|---|---|
`start.sh` | 8 (guarded `pip install`, `exec python3 app.py`)
`requirements.txt` | 1 (`flask==3.0.3`)
`app.py` | 56 (blueprints, `before_request` snapshot, ApiError/HTTPException handlers)
`store.py` | 73 (in-memory dicts + logical clock, empty on every boot)
`errors.py` | 50 (38-entry error catalog + `ApiError`)
`common.py` | 80 (Decimal `ROUND_HALF_UP`, quarter quantization, ISO-8601 with 3 fractional digits)
`envelope.py` | 96 (`meta`/`response_type`/`data`, pagination meta, version-bump bookkeeping)
`auth.py` | 66 (`X-User-ID`/`X-User-Role`, roles, center scope, designation authority)
`validate.py` | 163 (Band C payload/enum, pagination bounds, filters)
`calc.py` | 427 (all nine calculations + read helpers)
`cascade.py` | 188 (counter conservation, posture, cycle readiness, PREP<->PREP_BLOCKED)
`serializers.py` | 251 (13 entity serializers)
`routes/__init__.py` | 0
`routes/centers.py` | 250
`routes/config.py` | 229
`routes/cases.py` | 282
`routes/abstractions.py` | 169
`routes/pi.py` | 255
`routes/cycles.py` | 446

**Endpoints: 56** — `url_map` enumerates 57 rules, 56 of them application routes (the 57th is Flask's `/static`), a 1:1 match with the PRD §4 table.

## Smoke test (ports 41837 / 41839 / 41841, each killed by exact PID)

Verified live: center registration -> tier -> case (inclusion `INCLUDED`/`MEETS_INCLUSION_CRITERIA`) -> abstraction (OCC 412 on a stale `expected_case_version`) -> validate -> response log (`LATE`, 35 min vs a 15-min limit, spawning a `SYSTEM_AUTO DELAYED_SURGEON` event) -> triage review (persisted rate 100.00, audit variant 0.00 because the cohort predicates differ) -> outreach verify/reject ledger returning exactly to 0.00 -> lock -> referral agreement draft/activate. Full PI loop: start-review -> action -> `ERR_OPEN_ACTIONS_BLOCK_LOOP_CLOSURE` -> complete -> owner-verify blocked by `ERR_SEGREGATION_OF_DUTIES` -> verify -> close-loop (open 0/closed 1) -> reopen (round 2, due +30 d, actions reset to OPEN, counters restored). Full cycle path: booking refused before submit, `ERR_DESIGNATION_AUTHORITY_MISMATCH` for an SDO on a national cycle, submit at 82.00, schedule blocked until a booking made while `SUBMITTED` exists, a 24-hour gap accepted and a 24h-minus-1s gap rejected with `ERR_SURVEYOR_WINDOW_CONFLICT`, `ERR_CRITICAL_DEFICIENCY_BLOCKS_VERIFICATION`, then the CONTINGENCY four-hop cascade (2 escalations in ascending `criterion_code` order — confirmed `CD-2-05` before `CD-9-01` — 2 spawned 30-day `DEFICIENCY_ESCALATION` events, posture `SUSPENDED`, and a subsequent submit refused with `ERR_POSTURE_SUSPENDED`). A fresh reboot answers within ~1 poll and reports `total_count 0` on every collection; no seeding, no disk writes, `__pycache__` removed.

## PRD ambiguities and the interpretations chosen

- **Version bumps**: implemented as a per-request snapshot diff plus explicit `touch()` where the PRD says a version increments unconditionally (e.g. "both the cycle's and the center's version are bumped" on any deficiency recording, including non-critical classes). PRD §2.8 beats narrower scaffold prose.
- **Two clocks**: `created_at`/`updated_at` use wall time; only the enumerated `*_at` stamps and all deadline math use the logical clock, which never falls back to wall time.
- **Live vs persisted derivations**: center `readiness_posture` is recomputed at serialization (so merely advancing the clock past a `loop_closure_due_at` degrades posture with no write) while still being persisted on writes; cycle `readiness_score` stays the persisted reviewer value and the `/readiness` read computes live.
- **Cycle readiness refresh is opt-in per declared trigger**, and there is no gate evaluation at cycle creation — otherwise an unrelated write could silently drive a cycle to `PREP_BLOCKED` and make `ERR_READINESS_BELOW_THRESHOLD` unreachable. A cycle created with a score below 70.00 stays in `PREP` and is refused at submit with that error.
- **PREP<->PREP_BLOCKED**: blocked when score < 70.00 **or** `open_type_i_count >= 1`; unblocked only when both clear. Recording a critical deficiency while `UNDER_REVIEW` does not drag the cycle to `PREP_BLOCKED` (that would make the CONTINGENCY path unreachable).
- **`/readiness` output** omits `registry_penalty`, following the PRD's and the scaffold's explicit output list even though the penalty is one of the four inputs; `submit_eligible` is defined purely as `readiness_score >= 70.00`.
- **Failed submits are side-effect free**: the refreshed score is persisted only when submission succeeds.
- **Designation-authority check** is applied to exactly the five operations Band A names (decide, record deficiency, close deficiency, book surveyor, begin-review) — notably *not* escalate or schedule-site-visit.
- **`DEFICIENCY_ESCALATION` deadlines**: 30 days for both the single escalate and each CONTINGENCY hop-3 event; a manually opened event always gets 60 days, and a manual `DEFICIENCY_ESCALATION` is accepted (the PRD calls the value "reserved" but declares no error for it).
- **Missing-booking preconditions** on schedule-site-visit and begin-review are reported as `ERR_INVALID_CYCLE_STATE` (Band E names those two operations as cycle-state guarded, and no dedicated error exists); the "created while `SUBMITTED`" requirement is tracked with a private field on the booking.
- **Ordering compromise**: for record-borne authority/scope targets the record is loaded (404) before the Band A check; malformed or mistyped identifiers are 400 before unknown-id 404.
- Other picks carried over from the earlier modules: MRN uniqueness on `(center_id, mrn)` per the PRD rather than the scaffold's triple; surveyor buffer taken from the new booking's `travel_buffer_hours` (default 24); abstraction rejection restores the penalty capped at 100.00; second transfer-out and rescind-without-transfer -> `ERR_CASE_ALREADY_LOCKED`; triage review on an excluded case -> `ERR_TRIAGE_ALREADY_REVIEWED`.

## Unit test generation (test_helpers/ + test_suite/, task root)

Stage 1: 9 helper modules, 3824 lines (`api_client`, `api_errors`, `assertions`, `constants`, `factories`, `fixtures`, `test_users`, `types`, `__init__`). Stage 2: 17 test modules plus `conftest.py`, 94 tests, every docstring carrying exactly one `Design:` line.

Coverage: queue A (§1.8) 24/24 instances, 0 stubs, 2 tests each. Queue B (§1.9) 45/45 non-stub instances; the 25 `excluded_because:` stubs are all explicit dedupes against a §1.8 instance and were deliberately not emitted. No instance was skipped under the PRD-first filter.

Recipe-vs-PRD adjudications applied (PRD governs): `DOCUMENTATION_GAP`/`SYSTEM_ISSUE`/`RESPONSE_TIME` event types substituted with `MORTALITY_REVIEW`/`TRANSFER_DELAY`; `PROCESS_CHANGE` -> `PROTOCOL_CHANGE`; `review_status`/`reviewed_by_user_id` -> `validation_status`/`validated_by_user_id`; `SUPERSEDED` -> `REJECTED` + `rejection_reason SUPERSEDED_BY_RESUBMISSION`; `NOT_REVIEWED` -> `UNREVIEWED`; exact `data.message` assertions dropped; the `variant` echo asserted only when a non-default selector was sent; the `pi_loop_reopen_restores_open_closed_event_partition` sub-assertion that a reopened loop keeps its action VERIFIED contradicts PRD §3.7 and was not emitted.

## Step 5: Generate unit tests (subagent) — 2026-09-04T13:23:00.000Z

Test generation is complete. Both output directories are at the task root; `workspace/` still holds only `INSTRUCTION.md`, `PRD.md` and `implementation/` (never read or written).

## Coverage audit

**Queue A — `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (§1.8): 24 / 24 instances translated, 0 stubs, exactly 2 tests each.** All nine rules complete: `boundary_precision_check` (3), `combinatorial_formula` (3), `compensating_invariant` (3), `cross_entity_state_dependency` (3), `dual_variant_calc` (2), `non_linear_state_machine` (3), `priority_pair_validation_conflict` (3), `resource_temporal_overlap` (2), `transitive_cascade` (2).

**Queue B — `SCAFFOLD_CORNER_DESIGN.yaml` (§1.9): 45 / 45 non-stub instances translated.** The other 25 instances carry `excluded_because:` and are all explicit dedupes pointing at a §1.8 instance, so nothing was emitted for them.

**Instances skipped: none.** Every non-stub instance had verbatim PRD coverage and a uniquely-derivable outcome. What I did adjust were individual sub-assertions where a recipe contradicted the PRD (PRD governs): non-existent enum members substituted (`DOCUMENTATION_GAP`/`SYSTEM_ISSUE`/`RESPONSE_TIME` -> `MORTALITY_REVIEW`/`TRANSFER_DELAY`, `PROCESS_CHANGE` -> `PROTOCOL_CHANGE`), field renames (`review_status` -> `validation_status`, `NOT_REVIEWED` -> `UNREVIEWED`, `SUPERSEDED` -> `REJECTED` + `rejection_reason`), exact `data.message` assertions dropped, default-read `variant` echoes dropped, and one `pi_loop_reopen...` sub-assertion (action stays VERIFIED after reopen) omitted because PRD §3.7 says the opposite.

**Verification:** a programmatic scan confirms 94 tests, each with exactly one `Design:` line, zero untagged/dual-tagged tests, zero tags pointing at a non-existent instance, and zero stub instances translated. `pytest --collect-only` collects all 94 with no import errors (I added `ERROR_WEIGHT_CRITICAL/MAJOR/MINOR` to the `test_helpers/__init__.py` re-exports and switched three dictionary-rule call sites to the dedicated `range_/conformance_/required_rule_payload` factories so RANGE/CONFORMANCE rules stop sending explicit nulls).

## Files

`test_helpers/` — 9 modules, 3824 lines: `__init__.py` 175, `api_client.py` 521, `api_errors.py` 105, `assertions.py` 597, `constants.py` 124, `factories.py` 532, `fixtures.py` 1118, `test_users.py` 126, `types.py` 526.

`test_suite/` — `conftest.py` 33 lines (owns the `api`/`clock` fixtures; the runner plugin exposes none), then tests / lines:
`test_01_center_registration_and_configuration.py` 5/278 · `test_02_registry_case_intake_and_inclusion.py` 9/553 · `test_03_abstraction_dictionary_scan.py` 5/349 · `test_04_abstraction_adjudication_and_locking.py` 4/179 · `test_05_response_time_documentation.py` 3/185 · `test_06_triage_rate_variants.py` 4/255 · `test_07_under_triage_cascade.py` 2/146 · `test_08_referral_agreements_and_transfers.py` 6/317 · `test_09_pi_loop_lifecycle.py` 5/288 · `test_10_outreach_credit_ledger.py` 5/319 · `test_11_readiness_score_variants.py` 5/270 · `test_12_verification_cycle_progression.py` 7/356 · `test_13_deficiency_remediation_and_escalation.py` 3/227 · `test_14_surveyor_scheduling.py` 3/162 · `test_15_validation_precedence_and_authorisation.py` 11/547 · `test_16_error_and_existence_surface.py` 5/187 · `test_17_illegal_transitions.py` 12/621.

A "Unit test generation" section was appended to `worklog.md` by the subagent recording the same audit and the adjudication list. No server was started, so no process was killed.

**Orchestrator placement check:** `test_helpers/` and `test_suite/` are at the task root; `workspace/` contains only INSTRUCTION.md, PRD.md, implementation/ — no stray test directories to move before Step 7.

## Step 7: Run tests and iterate (long-lived subagent) — 2026-09-04T13:45:00.000Z

Clean 8-round sweep achieved.

## Summary

**Iterations run: 2**

**Final sweep (verified with my own eyes, `workspace/implementation/results.1..8.json`):**
```
results.1.json: passed=94 total=94 failed=0 errors=0
results.2.json: passed=94 total=94 failed=0 errors=0
results.3.json: passed=94 total=94 failed=0 errors=0
results.4.json: passed=94 total=94 failed=0 errors=0
results.5.json: passed=94 total=94 failed=0 errors=0
results.6.json: passed=94 total=94 failed=0 errors=0
results.7.json: passed=94 total=94 failed=0 errors=0
results.8.json: passed=94 total=94 failed=0 errors=0
```

**Iteration 1 diagnosis (18 failures, identical in all 8 rounds — fully deterministic, not flakiness):**

Every one of the 18 failures reported the same error: `KeyError: 'data'`. Per the STEP 0 -> triage-hint path (>=5 tests sharing one trace => suspect the test layer first), I reproduced against a live server I owned on port 17713 and traced it to a single mechanical misuse of the runner's assertion library in `test_suite/`:

`prd_bench_local_runner.testing.validate_success()` already returns `body["data"]` (it unwraps the envelope itself). 19 call sites wrote `validate_success(response, 201)["data"]`, double-indexing the already-unwrapped resource dict. The implementation's envelope was correct in every case — the tests never got as far as asserting anything.

**Tests deleted: none.** No test failed the STEP 1 coverage or unique-derivability checks; the sole defect was in the test layer's use of the helper, and it was repairable in the faithfulness-increasing direction (STEP 2).

**Fixes applied to `test_helpers/`: none.** The bug was in `test_suite/`, not in fixtures, factories, or role-header builders.

**Fixes applied to `implementation/`: none.** No implementation defect was found; no PRD-required check was weakened, no endpoint/field/side-effect was added, and storage remains in-memory only.

**Fixes applied to `test_suite/` (19 call sites across 10 files):** stripped the redundant `["data"]` from `validate_success(...)` so the tests assert against the resource object rather than raising `KeyError` before any assertion runs. No assertion was weakened — each test now actually evaluates the exact `error_id`, field, boundary, and status-transition checks it was written to evaluate.

- `test_01_center_registration_and_configuration.py:64`
- `test_02_registry_case_intake_and_inclusion.py:77, 361, 410, 425, 525, 539` (line 77 was a multi-line call needing a separate edit)
- `test_04_abstraction_adjudication_and_locking.py:174`
- `test_08_referral_agreements_and_transfers.py:131, 194`
- `test_12_verification_cycle_progression.py:179, 276`
- `test_13_deficiency_remediation_and_escalation.py:224`
- `test_14_surveyor_scheduling.py:102`
- `test_15_validation_precedence_and_authorisation.py:158, 213, 269, 319`
- `test_17_illegal_transitions.py:110, 191`

**Housekeeping:** my diagnostic server was killed by its specific PID via a port-`17713` lookup (no broad `pkill`); `__pycache__`/`.pytest_cache` artifacts and `workspace/sweep.log` were removed. The 8 `results.*.json` files are retained as evidence.

**Orchestrator independent verification:** re-read all 8 `results.$i.json` myself (each ~32 KB, mtime 13:40) and confirmed `passed=94 total=94 failed=0 errors=0` in every round. Sweep artifacts are real, not claimed.

**Orchestrator decision on Step 8:** the skip condition (0 deletions AND 0 test_suite fixes AND 0 test_helpers fixes AND 0 implementation fixes) is NOT met — there were 2 iterations and 19 `test_suite/` fixes — so Step 8 runs. Note however that the 19 fixes were a mechanical helper-misuse bug (double-unwrapping the response envelope) with no PRD-silence content, and there were 0 `implementation/` fixes, so a byte-identical or near-identical `PRD_FINALIZED.md` is a legitimate outcome here. Step 9 then does the full scan regardless.

## Step 8: Finalize PRD (subagent) — 2026-09-04T13:57:00.000Z

Done. `PRD_FINALIZED.md` was created and, after a full in-scope check, deliberately left byte-identical to `PRD.md`.

## Line counts
- `PRD.md`: 470 lines
- `PRD_FINALIZED.md`: 470 lines
- delta: 0 lines, 0.00% (`diff` reports no difference)

## Changes
None. Zero inserts, zero revisions.

## Scope analysis / pre-edit search log

The whole Step 7 diff is one subject, so the mandatory enumeration was run once against it and it produced no edit.

(a) **Subject identified:** the success/error response envelope contract — specifically what lives directly under `data` — i.e. PRD §2.2 (with §2.3 pagination `meta` and §2.4 clock echo as adjacent surfaces).

(b) **Impl paths enumerated (read/grepped):**
- `envelope.py:77-99` — `respond_object` emits `{"meta": ..., "response_type": "object", "data": data}`; `respond_list` emits `response_type: "array"` with `meta(page)` merging `limit/offset/total_count/has_more`; `error_body` emits `meta` with exactly `api_request_id` + `api_request_timestamp`, `response_type: "error"`, `data: {error_id, message}`.
- Every envelope callsite in the impl (grepped `respond_object|respond_list|error_body|jsonify`): `routes/centers.py:88,96,111,140,151,169,202,214,238,250`; `routes/cases.py:99,107,126,150,173,201,223,268,282`; `routes/abstractions.py:110,121,142,169`; `routes/cycles.py:100,108,119,141,182,194,220,238,268,305,316,341,359,374,446`; `routes/pi.py:90,98,109,120,154,165,186,205,228,255`; `routes/config.py:75,86,132,155,175,188,212,229`; `app.py:30,36,38,40,41,46`. Every single one passes the serialized resource (or a documented computed payload) as `data` with no extra nesting layer — uniform, no off-Step-7 outlier.
- The two non-resource `data` payloads (`routes/centers.py:155-169` triage-rate read, `routes/cycles.py:125-141` readiness breakdown) are already field-for-field documented in `PRD.md:254` and `PRD.md:330`; the clock echo (`routes/config.py:188`, `{"current_utc": ...}`) is documented in PRD §2.4. So §2.2's existing "resource object or an array of resource objects" wording is not contradicted anywhere.
- No `DELETE`/`PUT` routes exist, so PRD's "2xx responses with no data -> empty object" clause is unexercised rather than mismatched.
- Runner helper `prd_bench_local_runner/testing/validators.py:27-50` — `validate_success` itself asserts envelope shape and `return body["data"]`.
- Spot-checked 6 of the 19 fixed callsites (`test_01:64`, `test_02:77`, `test_04:174`, `test_08:131`, `test_12:179`, `test_14:102`): after the fix each asserts plain resource fields (`name`, `abstraction_status`, `locked_at`, `status`, `travel_buffer_hours`, ...) that the corresponding serializers already emit. None targets a computed-payload endpoint.
- Confirmed no `validate_success(...)["data"]` double-unwrap survives anywhere in `test_suite/`.

(c) **Wording adjustment:** none required — and none made. PRD §2.2 already uniquely determines the behavior the implementation exhibits.

## Key finding
The 18 deterministic failures were entirely a `test_suite/` misuse of `validate_success` (double-indexing an already-unwrapped envelope). That is a pure test-harness bug: it reveals neither PRD silence nor PRD/impl divergence. With zero implementation fixes, zero test deletions, and zero weakened assertions in the Step 7 diff, the HARD SCOPE admits no edit, so any change would have been manufactured out-of-scope work and a new-mismatch risk for Step 9. One caveat deliberately left unpinned because Step 7 never exercised it: `envelope.py:22` stamps `meta.api_request_timestamp` from `wall_now()` (host wall clock) rather than the logical clock, and generates `api_request_id` as `req_` plus 20 uppercase-alphanumeric characters — PRD §2.2 constrains only the format and the `req_` prefix, not the clock source or the suffix length.

**Orchestrator note:** a byte-identical `PRD_FINALIZED.md` is the correct outcome when Step 7 made zero `implementation/` fixes — the Step 8 mandate is bounded to PRD silences/mismatches revealed by the Step 7 diff, and a harness helper-misuse bug reveals none. Step 9 (which always runs and is not diff-bounded) will do the full PRD-vs-implementation scan, including the envelope caveat flagged above.

## Step 9: Complete PRD — eliminate residual ambiguity and mismatch (3 sequential partitioned subagent passes) — 2026-09-04T14:22:00.000Z

**Orchestrator design decision:** a single-shot full PRD-vs-implementation scan reliably under-covers a 19-module implementation (the known failure mode is an output byte-identical to the input, i.e. the scan never really ran). Step 9 was therefore executed as THREE SEQUENTIAL subagent passes over one shared `PRD_COMPLETED.md`, partitioned by implementation module. Pass 1 owned the `cp`; passes 2 and 3 were explicitly forbidden from copying, and each was told the current line count so it could detect clobbering. Each pass was also given the unresolved items the previous pass handed forward.

- Pass 1 partition (global/cross-cutting layer -> PRD §2): `app.py`, `envelope.py`, `store.py`, `common.py`, `errors.py`, `auth.py`, `validate.py`, `serializers.py`
- Pass 2 partition (calculations, cascades, intake half -> PRD §3.1–§3.6, §4): `calc.py`, `cascade.py`, `routes/centers.py`, `routes/config.py`, `routes/cases.py`, `routes/abstractions.py`
- Pass 3 partition (PI loop + verification cycle -> PRD §3.7–§3.9, §4): `routes/pi.py`, `routes/cycles.py`

### Pass 1 (12 ambiguity-pins, 1 mismatch-revision; 470 -> 477 lines)
- §2.1 — revise — ambiguity — identity headers: empty header value counts as absent; role matched case-sensitively/exactly against the seven -> 401 — `auth.py:26-29`
- §2.2 — revise — ambiguity — `api_request_id` = `req_` + exactly 20 chars from `A`–`Z`/`0`–`9`, minted fresh per response including errors — `envelope.py:12-16`
- §2.2 — revise — ambiguity — `api_request_timestamp` stamped from the host wall clock, not the logical clock (Step 8 handoff item, adjudicated) — `envelope.py:22`, `common.py:32`
- §2.2 — insert — ambiguity — transport-level failures: unknown path -> 404 `ERR_REFERENCED_RESOURCE_NOT_FOUND`; unsupported method -> `ERR_INVALID_REQUEST` on HTTP 405 (only case where that id is not 400); unparseable/non-object body -> 400; unhandled fault -> 500; trailing slash tolerated — `app.py:17,33-46`
- §2.3 — revise — ambiguity — non-integer `limit`/`offset` -> 400; empty-string value treated as omitted — `validate.py:124-143`
- §2.3 — revise — ambiguity — `created_at` ties broken by server creation order (total, stable); filters applied before pagination — `common.py:75-80`
- §2.3 — insert — ambiguity — list filters are exact string equality, never enum-validated (out-of-enum filter -> empty page, not 422); empty filter treated as omitted — `validate.py:159-163`
- §2.4 — revise — ambiguity — every documented property always present, `null` when unset; internal bookkeeping keys never exposed — `serializers.py` (all builders, `_audit` 8-13)
- §2.4 — revise — ambiguity — `created_at`/`updated_at` wall-clock stamped; all records mutated by one request share one `updated_at` instant — `common.py:66-72`, `envelope.py:57,73`
- §2.4 — revise — ambiguity — the logical-clock `*_at` list is exhaustive; `created_at`/`updated_at`/`api_request_timestamp` are the wall-clock fields — `common.py:32,67`
- §2.4 — insert — ambiguity — client timestamp parsing (`Z` / explicit offset / naive-as-UTC / date-only-as-midnight; unparseable -> 400); date-named fields are full 3-digit instants, not bare dates; store in-memory and empty at boot — `common.py:36-59`, `validate.py:87-106`, `store.py:36-51`
- §2.6 — revise — ambiguity — "2 decimals" is the value not the literal: JSON numbers may print as `100.0`/`0.0`; `credit_hours` echoed at 3 decimals; `band_multiplier_used` as `1.0`/`1.5`/`2.0` — `common.py:22-24`, `serializers.py:94,214`
- §2.6 — revise — **mismatch** — PRD said timestamp comparisons are "evaluated at second granularity"; impl compares the whole stored instant with no truncation (only rendering truncates to 3 digits) — `common.py:54-59`
- §2.7 — revise — ambiguity — `readiness_posture` re-evaluated at response time from persisted counters/rates/status plus the logical clock, so a clock-only degradation shows without touching `updated_at`/`version` — `serializers.py:27`, `cascade.py:59-62`
- §2.8 — revise — ambiguity — version bump once per request per record (not per touch); a record created by the request ends at `version` 1 with `updated_at == created_at`; `DataDictionaryRule` outside the bookkeeping — `envelope.py:50-74`, `store.py:16-29`
- §2.11 Band C — revise + insert — ambiguity — `variant` is a query parameter (still 422 when out of enum) while list filters are not enum-checked; presence judged by value; required strings non-blank; booleans rejected for int/number; fractional rejected for int; body parsed as JSON regardless of `Content-Type`; absent/empty body read as `{}` — `validate.py:11-121`

### Pass 2 (22 ambiguity-pins, 4 mismatch-revisions; 477 lines, all in-paragraph)
- §2.7 — insert — ambiguity — the `readiness_posture` list filter matches the same response-time evaluation the representation reports, not a persisted field — `routes/centers.py:107-109`
- §2.8 — insert — ambiguity — "every cycle's readiness score" is exactly the six not-yet-decided statuses; only `VERIFIED`/`DENIED` are skipped — `cascade.py:14-21,162-165`
- §2.8 — revise — **mismatch** — the `PREP <-> PREP_BLOCKED` gate is `score < 70.00` **or** `open_type_i_count >= 1`, both directions; PRD had stated it score-only — `cascade.py:144-152`
- §2.11 — insert — ambiguity — a numeric field outside a declared inclusive band is `ERR_INVALID_REQUEST` (Band C), not a business error — `validate.py:50-84`
- §3.1 — revise — ambiguity — malformed `state_code` is `ERR_INVALID_REQUEST` — `routes/centers.py:60-61`
- §3.1 — revise — ambiguity — unrecognised `field_name` is 400 not 422; `RANGE` requires both numeric bounds and `CONFORMANCE` a non-empty string array (both 400, before the enum checks); unused bounds/codes discarded — `routes/config.py:40-70`
- §3.2 — insert — ambiguity — unresolvable `transfer_in_from_center_id` is `ERR_CENTER_NOT_FOUND` checked after `center_id`; the tier need not belong to `center_id` — `routes/cases.py:59-65`
- §3.2 — insert — ambiguity — a latest-validated abstraction with null `iss_abstracted` leaves the arrival-recorded score standing, with no fallback to an older validated record — `calc.py:97-102`
- §3.2 — insert — ambiguity — opening a case rewrites the cohort partition and posture but recomputes neither the persisted triage rates nor any cycle readiness — `routes/cases.py:98`
- §3.3 — insert — ambiguity — `iss_abstracted`/`gcs_arrival` carry no range constraint at submission — `routes/abstractions.py:42-43`
- §3.3 — insert — ambiguity — a supersede is not an adjudication: `validated_by_user_id` stays null and no penalty points are restored — `routes/abstractions.py:83-86`
- §3.3 — insert — ambiguity — the scan reads the payload as it arrived: empty string counts as supplied, `ed_departure_at` scanned as raw text, `RANGE` never fires on a non-number, `CONFORMANCE` compares after string coercion — `calc.py:178-197`, `routes/abstractions.py:60-65`
- §3.3 — insert — ambiguity — rejection adds back the full `applied_penalty_points` even when the 0.00 floor clipped part of the deduction, capped at 100.00 — `routes/abstractions.py:166-167`
- §3.4 — insert — ambiguity — no ordering constraint between `notified_at` and `arrived_at`; a negative interval is recorded and resolves `COMPLIANT` — `calc.py:243-250`
- §3.4 — insert — ambiguity — the auto `DELAYED_SURGEON` event carries the triggering `case_id` and null `source_deficiency_id`, with **no** de-duplication (unlike §3.5) — `routes/cases.py:259-267`
- §3.5 — insert — ambiguity — an `EXCLUDED` case is refused with `ERR_TRIAGE_ALREADY_REVIEWED` (409), and the unreviewed test runs first — `routes/cases.py:162-166`
- §3.5 — revise — **mismatch** — all three triage outcomes unconditionally refresh every not-yet-decided cycle's readiness (§3.9's trigger list omitted this) — `routes/cases.py:172`, `cascade.py:171-183`
- §3.5 — revise — ambiguity — `variant` tokens `PROVISIONAL_MONITORING`/`VERIFICATION_AUDIT`, the default on omitted-or-empty, and the exact six-property response with no `id`/audit properties — `routes/centers.py:32,159-169`
- §3.6 — insert — ambiguity — both centers reported as `ERR_CENTER_NOT_FOUND` (referring first) and the two need not differ (self-agreement accepted) — `routes/config.py:104-111`
- §3.6 — insert — ambiguity — the `direction` filter's nine accepted tokens, case-insensitive/trimmed, anything else falling back to both directions — `routes/centers.py:33-34,224-235`
- §3.6 — revise — ambiguity — a second transfer-out is `ERR_CASE_ALREADY_LOCKED` — `routes/cases.py:188-189`
- §3.6 — revise — **mismatch** — transfer-out also refreshes every not-yet-decided cycle's readiness — `routes/cases.py:200`
- §3.6 — revise — ambiguity — rescinding with no recorded transfer-out is `ERR_CASE_ALREADY_LOCKED`; `rescind_reason` stored but not returned — `routes/cases.py:214-218`
- §3.6 — revise — **mismatch** — rescission also refreshes every not-yet-decided cycle's readiness — `routes/cases.py:222`
- §3.8 — insert — ambiguity — `REJECTED -> VERIFIED` leaves the prior `rejection_reason` in place — `routes/config.py:206-212`
- §4 (`GET /trauma-centers` row) — revise — ambiguity — the filters are exactly `state_code` and `readiness_posture` — `routes/centers.py:104-109`

**Pass 2 correction of a pass-1 handoff:** pass 1 reported that `GET /trauma-centers` filters on the *stored* `readiness_posture` and could disagree with the representation. Pass 2 read `routes/centers.py:107-109` and found it filters on `cascade.posture_of(r)` — the same live evaluation `serializers.center` uses — so filter and representation always agree. Pass 2 pinned the behavior as the code actually is, not as the handoff described it.

### Pass 3 (14 ambiguity-pins, 8 mismatch-revisions; 477 lines, all in-paragraph)
- §3.7 — revise — **mismatch** — `DEFICIENCY_ESCALATION` is not actually reserved: manual creation accepts it with `origin` `MANUAL`; `case_id` existence-checked but `source_deficiency_id` not; creation refreshes only not-yet-decided cycles with the §2.8 gate applied — `routes/pi.py:25-31,72-89`
- §3.7 — insert — ambiguity — corrective action: `owner_user_id` not existence-checked, `due_at` unconstrained (a past date accepted), `completion_note` initialised null and always reported, center untouched — `routes/pi.py:129-154`
- §3.7 — insert — ambiguity — completion requires TPM center scope (`ERR_CENTER_SCOPE_VIOLATION`); no counter recompute; no center touch — `routes/pi.py:171-186`
- §3.7 — revise — **mismatch** — "completing an already-`VERIFIED` action is `ERR_INVALID_ACTION_STATE`" is false when the parent event is illegal: event state is tested first -> `ERR_INVALID_PI_STATE`; verify imposes no parent-event precondition — `routes/pi.py:177-181,194-195`
- §3.7 — revise — **mismatch** — loop closure's `PREP_BLOCKED -> PREP` also requires `open_type_i_count == 0`; `loop_closure_note` is a reported property — `cascade.py:144-152`
- §3.7 — insert — ambiguity — reopen clears `completed_at`/`verified_at`/`verified_by_user_id` but retains `completion_note` and the old `loop_closure_note`; `OPEN`/`COMPLETED` actions untouched; `reopen_reason` reported — `routes/pi.py:240-252`
- §3.9 — insert — ambiguity — cycle creation reports a `decision` property (null) and is the one recomputation that stores readiness **without** the gate, so a sub-70 cycle is still born in `PREP`; no center bump — `routes/cycles.py:80-99`
- §3.9 — revise — **mismatch** — readiness trigger list extended (escalation, triage adjudication, transfer-out, rescission, delayed-surgeon, `CONTINGENCY` decision) plus the single-cycle vs all-cycles split and the abstraction path's `CONTINGENCY` exclusion — `cascade.py:14-30,171-183`; `routes/cases.py:172,200,222,267`
- §3.9 — insert — ambiguity — readiness read: literal `variant` tokens, default, exhaustive 7-property response, `submit_eligible` derived from the requested variant, `registry_penalty` deliberately unreported, no persistence, no audit props — `routes/cycles.py:127-141`; `calc.py:327-367`
- §3.9 — insert — ambiguity — `ERR_CYCLE_NOT_FOUND` precedes `ERR_DESIGNATION_AUTHORITY_MISMATCH` — `routes/cycles.py:151-152`; `auth.py:58-61`
- §3.9 — revise — **mismatch** — deficiency recording moves to `PREP_BLOCKED` only *from* `PREP`; `escalation_reason` starts null and is reported; `criterion_code` free-form/non-unique; center `version` bump unconditional even for `TYPE_III_MINOR` — `routes/cycles.py:162-182`; `cascade.py:149`
- §3.9 — insert — ambiguity — escalation is not authority-matched, and it refreshes its own cycle *and* every other not-yet-decided cycle, bumping the cycle's `version` — `routes/cycles.py:241-267`
- §3.9 — revise — **mismatch** — deficiency closure's `PREP_BLOCKED -> PREP` also requires `open_type_i_count == 0`; no payload; no forced center bump — `routes/cycles.py:223-238`; `cascade.py:148`
- §3.9 — insert — ambiguity — `travel_buffer_hours` is an integer >= 0 (negative = `ERR_INVALID_REQUEST`); a booking bumps no cycle/center version — `routes/cycles.py:284`
- §3.9 — revise — **mismatch** — the pad is the *requested* booking's `travel_buffer_hours`, not a flat 24; candidates' own stored buffers are ignored — `calc.py:394-412`
- §3.9 — insert — ambiguity — submission also rewrites the three per-class counters, reads the live §2.7 posture, and touches no center field — `routes/cycles.py:331-340`
- §3.9 — insert — ambiguity — schedule-site-visit is *not* authority-matched (begin-review is); a booking made after `SITE_VISIT_SCHEDULED` does not satisfy the requirement — `routes/cycles.py:344-355`
- §3.9 — insert — ambiguity — all three decisions write `decision_effective_date` verbatim (no ordering constraint), set `decision`, set `status` to the same literal, and bump the center's `version` — `routes/cycles.py:391-397,437-445`
- §3.9 — insert — ambiguity — CONTINGENCY hop 2 tie-breaks by `created_at` and leaves `escalation_reason` null — `routes/cycles.py:424-427`
- §3.9 — insert — ambiguity — the readiness refresh is CONTINGENCY-only (gate not evaluated); `VERIFIED`/`DENIED` keep the frozen score; other cycles refresh only when something escalated — `routes/cycles.py:439-443`
- §3.9 — revise — **mismatch** — terminality of `VERIFIED`/`DENIED` covers cycle-addressed writes only; remediating/closing/escalating a decided cycle's deficiency is legal and *does* rewrite the frozen `readiness_score` — `routes/cycles.py:209,230,249` (no cycle-state guard)

**Pass 3 handoff disposition:** (1) §3.9 trigger list extended — no longer contradicts §3.5/§3.6. (2) `open_type_i_count == 0` conjunct fixed at §3.9 deficiency closure AND at §3.7 loop closure, which carried the identical defect. (3) `registry_penalty` omission adjudicated as already-correct; tightened to "exactly seven properties and nothing else" with the penalty named as an input that is not reported. (4) `REVIEWER_ASSESSMENT`/`SELF_ASSESSMENT` literals + default + `ERR_INVALID_ENUM_VALUE` pinned, mirroring pass 2's §3.5 treatment. (5) flat-24 rule replaced by the requested booking's `travel_buffer_hours` (default 24).

### Aggregate
- Source `PRD_FINALIZED.md` 470 lines -> `PRD_COMPLETED.md` 477 lines (+7, +1.49%); 222 diff lines versus the source.
- Totals across the three passes: **48 ambiguity-pins, 13 mismatch-revisions** (61 changes).
- Zero deletions: every diff hunk is a change, none a delete, so no pass clobbered an earlier pass.

### Orchestrator final verification (independent)
- `PRD_COMPLETED.md` is 477 lines and DIFFERS from `PRD_FINALIZED.md` (222 diff lines) — the scan demonstrably ran; a byte-identical Step 9 output would have meant it did not.
- §1–§5 headings all present (lines 3 / 11 / 188 / 374 / 437); §4 endpoint table 56 data rows (57 incl. header); §5 error table 37 rows; file ends on the complete `ERR_READINESS_BELOW_THRESHOLD` row, a real section boundary.
- No file under `workspace/implementation/`, `test_suite/`, or `test_helpers/` was modified after the 13:40 green sweep — Steps 8 and 9 were PRD-only, so the verified 8×94/94 result still describes the shipped artifacts.

## Pipeline complete — Step 9 has written workspace/PRD_COMPLETED.md.
