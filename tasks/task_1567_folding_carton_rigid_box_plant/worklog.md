# Worklog — task_1567_folding_carton_rigid_box_plant

## Step 1: Create Task Directory — 2026-08-13T21:35:00.000Z

Task directory `tasks/task_1567_folding_carton_rigid_box_plant/` and its `workspace/` subdirectory were pre-created and pre-assigned by the pipeline launcher. Step 1 treated as DONE per instructions; no index scan performed, no other task directory touched.

## Step 2: Generate Scaffold — 2026-08-13T22:39:00.000Z (resume-run verification)

RESUME RUN note: a prior run of this pipeline was killed after Step 2 completed but before its summary was logged. On resume, the orchestrator verified all three artifacts exist and are complete/valid rather than regenerating them:
- `SCAFFOLD.yaml` (82,997 bytes) — parses as valid YAML; top-level keys: scenario, domain_name, api_prefix, complexity_profile, response_envelope, entities, state_machines, concurrency_rules, calculations, validations, endpoints, errors. File ends cleanly in §1.7 concurrency_rules content (no truncation).
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (96,204 bytes) — valid YAML; single top-level key `scaffold_difficulty_design`; ends cleanly mid §1.9 worked-example content (no truncation).
- `SCAFFOLD_CORNER_DESIGN.yaml` (63,317 bytes) — valid YAML; single top-level key `scaffold_corner_design`; ends cleanly in boundary-instance worked-example content (no truncation).
All three kept and reused per the resume contract.

## Step 3: Copy Shared Files — 2026-08-13T22:45:00.000Z

Copied `./INSTRUCTION.md` to `tasks/task_1567_folding_carton_rigid_box_plant/workspace/INSTRUCTION.md` (1,424 bytes).

## Step 4: Generate PRD — 2026-08-13T23:10:00.000Z

PRD generated at `/home/ubuntu/github/CodingPRD/tasks/task_1567_folding_carton_rigid_box_plant/workspace/PRD.md` (342 lines). The forbidden design-index files were never opened; no sibling task directories were touched.

**Document structure** — domain-derived skeleton, no template copying:
- §1: two paragraphs (business pain → system scope), `/plant` mount named
- §2.1 roles (7 exact spellings + identity prose: `BrandQuality` entity-backed by `Customer`, six opaque roles); §2.2 emitted byte-verbatim from `section-2.2-response-structure.md` (diff-verified); §2.3 pagination (limit 10/1/100, offset 0, `created_at` ascending, meta fields); §2.4 units/integer arithmetic/three rounding disciplines; §2.5 common properties + the two OCC rules; §2.6 the full 11-tier validation pipeline in explicit order; §2.7 INV-SHEETS; §2.8 INV-CARTONS; §2.9 logical clock (startup 2026-08-01T00:00:00Z) + half-open vs padded-closed window semantics; §2.10 cascade atomicity
- §3: 8 subsections by lifecycle narrative (customers/standards → intake/routing/quote → design/layout/press-ready gating → color verification → pressroom → finishing → kitting/retail/completion → invoicing/settlement), with constants embedded in prose, per-line rounding pin including the 111532 vs 111531 worked example, and all cascades narrated level-by-level
- §4: 78-row endpoint table, 4 columns only; §5: 39-row error table, 2 columns only

**Hard Contract Reports:**

```
Field coverage check:
- entities[].fields: 95 required, 95 present, 0 missing
- endpoints[].request_body: 66 required, 66 present, 0 missing
- endpoints[].query_params: 11 required, 11 present, 0 missing
- endpoints[].path_params: 13 required, 13 present (inside backticked §4 paths), 0 missing
Status: PASS

Rule coverage check:
- validations[] with priority: 11 checked, 11 expressed in ordered §2.6 prose, 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (design-revision create + imposition-plan lock; expected_job_version + ERR_STALE_JOB_VERSION/412 named), 0 missing
- state_machines[].transitions: 34 checked, 34 fully expressed (all from→to pairs verified co-present in §2/§3 prose), 0 missing
- calculations[]: 7 checked (nesting_yield, route_selection, provisional_quote, final_settlement, minimum_makeready_recovery, sheet_allocation, kitting_consumption, retail_compliance_verdict), all formulas + constants + precision in reconstructible prose, 0 missing
- validations[] conditions: all matchable to their error_ids in §2/§3 prose; all 39 error IDs appear in §2/§3, 0 missing
- endpoints[].side_effects / applies_to: all expressed (standard-approve L1–L3 cascade, design-supersede cascade, job-cancel cascade, booking-completion 3-level cascade, allocation return, invoice uniqueness release), 0 missing
- entities[].fields[] structured content: defaults (QUOTED/DRAFT/SUBMITTED/SCHEDULED/ACTIVE/PLANNED), zero-initialized counters, computed-field derivations (good_cartons_actual, available_cartons, available_sheets, consumed_per_kit, allocated_cartons) all reconstructible, 0 missing
- sibling-branch symmetry: NORMAL/ROTATED, OFFSET/DIGITAL spoilage, accept/reject, approve/reject, certify/reject, settle/void, LENGTHWISE/WIDTHWISE — equal density, 0 asymmetric
Status: PASS

Path purity check (§3 only):
- backtick tokens scanned: 551
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

## Step 5: Generate Unit Tests — 2026-08-13T23:37:00.000Z (resume-run verification)

RESUME RUN note: the prior run was killed after Step 5's files were written but before its summary was logged. On resume, the orchestrator verified completeness rather than regenerating:
- `test_helpers/` — 9 modules (`__init__.py`, `types.py`, `api_client.py`, `api_errors.py`, `assertions.py`, `factories.py`, `constants.py`, `test_users.py`, `fixtures.py`), all compile clean under `py_compile`, file tails end cleanly (no truncation).
- `test_suite/` — `conftest.py` + 7 test files, 50 test functions total; all 50 carry exactly one `Design: Difficulty/...` or `Design: Corner/...` docstring tag (5/10/5/9/5/6/10 per file); `pytest --collect-only` collects 50/50 with no import errors.
- Both kept and reused per the resume contract.

## Step 6: Generate Implementation — 2026-08-13T23:37:00.000Z (resume-run verification)

RESUME RUN note: the prior run was killed after Step 6's files were written but before its summary was logged. On resume, the orchestrator verified completeness rather than regenerating:
- `workspace/implementation/` — `app.py` + 7 support modules + 17 route modules, all compile clean; `start.sh` executable, reads `$PORT`, binds `0.0.0.0`, runs foreground via `exec python3 app.py`, conditional pip install; `requirements.txt` = flask>=2.2; in-memory storage only.
- Smoke test: server boots from fresh process on a test port and serves the mounted API with the PRD §2.2 error envelope (`{"data":{"error_id":...},"meta":{...},"response_type":"error"}`); `prd-bench-local-run` runner binary present.
- Kept and reused per the resume contract.

## Step 7: Run Tests and Iterate — 2026-08-13T23:44:00.000Z

All 8 rounds of the stability sweep pass 50/50. Exiting with the summary.

## Summary

**Iterations run:** 2 (initial sweep → 1 fix → clean confirmation sweep).

**Tests deleted:** None.

**Failing tests (union across rounds, sweep 1):**
- `test_04_state_machine_loops_and_lockdowns.py::TestDesignRevisionSampleRejectLoop::test_brand_reject_loops_sample_back_to_draft` — failed all 8 rounds with `assert 1 == 2`.
- `test_04_state_machine_loops_and_lockdowns.py::TestDesignRevisionSampleRejectLoop::test_loop_reuses_same_revision_number` — flaky in sweep 1 console stream (same root cause via the shared helper).

**Diagnosis:** Both tests call the class-local helper `_sample_made_revision`, which created a design revision, called `make_sample`, but returned the **stale creation response** (version 1) instead of the `make_sample` response (version 2). The first test then asserted `revision["version"] == 2`, which could never hold against the stale dict. The PRD rule asserted (§2.5: "`version` ... increments by one on every mutation of the resource") is verbatim-covered and uniquely derivable — the expected sequence create=1 → make-sample=2 → reject=3 → make-sample=4 → accept=5 is correct, and the implementation in `/home/ubuntu/github/CodingPRD/tasks/task_1567_folding_carton_rigid_box_plant/workspace/implementation/routes/design_revisions.py` (`touch()` on every mutation) already implements it faithfully. STEP 2 outcome: TEST IS WRONG (stale-response bug in the test artifact).

**Fixes applied to `test_helpers/`:** None (the bug lived in a test-class-local helper, not in `test_helpers/`).

**Fixes applied to `test_suite/`:**
- `/home/ubuntu/github/CodingPRD/tasks/task_1567_folding_carton_rigid_box_plant/test_suite/test_04_state_machine_loops_and_lockdowns.py` — in `TestDesignRevisionSampleRejectLoop._sample_made_revision`, capture and return the `make_sample` response (version 2, status `SAMPLE_MADE`) instead of discarding it and returning the stale creation response. This makes both tests in the class evaluate the PRD-faithful version sequence against fresh server state.

**Fixes applied to `implementation/`:** None — the implementation was already PRD-faithful.

**Final state:** sweep 2 — all 8 parallel rounds report `passed=50 failed=0 errors=0 total=50`.

## Step 8: Finalize PRD — 2026-08-13T23:47:00.000Z

## Summary

**PRD.md vs PRD_FINALIZED.md:** 342 lines vs 342 lines, 0% delta — byte-identical (verified via `diff -q`).

**Changes:** None. The single Step 7 item was a pure test-artifact bug (the class-local helper `_sample_made_revision` discarded the `make_sample` response and returned the stale creation response), not a PRD silence or PRD/impl mismatch.

**Verification performed (required by the task note):**

- **PRD §2.5 passage read** (PRD.md line 80-90): "`version` (integer): a system-managed integer that increments by one on every mutation of the resource, including mutations caused by cascading side effects from operations on other resources." This uniquely pins the version-on-every-mutation rule for every resource, including design revisions.
- **Implementation read** (`/home/ubuntu/github/CodingPRD/tasks/task_1567_folding_carton_rigid_box_plant/workspace/implementation/routes/design_revisions.py`): `make_sample` (line 109), and `brand_accept`/`brand_reject` via `_brand_adjudicate` (line 124), both call `touch(rec)` on the revision.
- **Helpers read**: `util.touch` (`implementation/util.py:51-54`) does `rec["version"] += 1` on every mutation; `db.new_record` (`implementation/db.py:21-29`) initializes `version` at 1 on creation.
- The expected sequence create=1 → make-sample=2 → reject=3 → make-sample=4 → accept=5 is therefore uniquely derivable from §2.5 plus the design-revision state machine (each transition mutates the revision), and the implementation already realizes it faithfully.

**Pre-edit search log:** No edits were committed, so no pre-edit search was triggered for any edit. The verification reads above (subject: design-revision `version` increment on `make_sample`/`brand-reject`/`brand-accept`; paths enumerated: `design_revisions.py` create/make_sample/_brand_adjudicate/brand_accept/brand_reject, `util.py:touch`, `db.py:new_record`) confirmed the PRD passage already covers every impl path touching the subject, so no wording change was needed.

**Output file:** `/home/ubuntu/github/CodingPRD/tasks/task_1567_folding_carton_rigid_box_plant/workspace/PRD_FINALIZED.md` (byte-identical copy of PRD.md).

## Step 9: Complete PRD — 2026-08-13T23:58:00.000Z

All edits are applied and the diff is clean. Here is the final summary.

## Summary

**File**: `/home/ubuntu/github/CodingPRD/tasks/task_1567_folding_carton_rigid_box_plant/workspace/PRD_COMPLETED.md`

**Source vs. result**: `PRD_FINALIZED.md` (342 lines, 59,483 chars) → `PRD_COMPLETED.md` (345 lines, 62,753 chars); char-delta **+3,270**. The +3 lines come from one new inline paragraph in §2.2 and one new table row in §5; all other changes are in-paragraph inserts/revisions. No new sections added.

**Counts**: 16 ambiguity-pins, 4 mismatch-revisions (20 edit sites total).

### Ambiguity pins (insert)
- §2.2 — insert — ambiguity — unknown path / unsupported method return `ERR_NOT_FOUND` (404) in the error envelope; unexpected failure returns `ERR_INTERNAL` (500) — app.py:36-47
- §2.3 — insert — ambiguity — non-numeric `limit`/`offset` fall back to defaults, out-of-range values are clamped (limit 1–100, offset ≥ 0) not rejected; `created_at` ties break by insertion order; `has_more` is true iff `offset` + items returned < `total_count` — routes/common.py:82-95,122, response.py:29
- §2.5 — insert — ambiguity — `version` starts at 1 at creation — db.py:27
- §2.6 (third) — insert — ambiguity — brand-ownership check reads the acted-on resource, so a nonexistent target surfaces `ERR_NOT_FOUND` before any ownership check — routes/color_standards.py:93-95
- §2.6 (fifth) — insert — ambiguity — enumerated the twelve zero-admitting integer fields (non-negative only) vs. all others at least one; `start_utc`/`end_utc`/`to_iso8601` must be parseable ISO 8601 datetimes — routes/common.py:45-51, routes/press_bookings.py:49-51, routes/clock.py:20-23
- §2.6 (sixth) — insert — ambiguity — on the two OCC writes, the `expected_job_version` comparison is evaluated immediately after the job-state check — routes/design_revisions.py:44-50, routes/imposition_plans.py:124-130
- §2.9 — insert — ambiguity — clock set accepts any parseable timestamp (past or future), echoes the submitted string verbatim as `current_utc` — routes/clock.py:15-26
- §3.1 — insert — ambiguity — set-status to the status a customer already holds is rejected `ERR_INVALID_STATE_TRANSITION` (409) — routes/customers.py:54-56
- §3.1 — insert — ambiguity — `tolerance_delta_e_milli` is non-negative, `l_target` is an unconstrained integer, submit defined only from `DRAFT` — routes/color_standards.py:40-43,82-84
- §3.2 — insert — ambiguity — `required_ink_slots` is an array of strings, possibly empty; blank fitting the standard quoting sheet in no orientation rejects job creation with `ERR_LAYOUT_IMPOSSIBLE` (409) — routes/jobs.py:68-71,103-106
- §3.2 — insert — ambiguity — job cancellation retains `board_stock_id` while releasing the reservation — routes/jobs.py:303 (clear_stock_ref=False)
- §3.3 — insert — ambiguity — manual plan supersede is also rejected once the job is `CANCELLED`, not only `IN_PRODUCTION`+ — routes/imposition_plans.py:31,150-152
- §3.5 — insert — ambiguity — same-status press set-status rejected 409; new booking's `sheets_printed`/`sheets_good` are null until reported — routes/presses.py:70-72, routes/press_bookings.py:100-101
- §3.6 — insert — ambiguity — same-status finishing-line set-status rejected 409 — routes/finishing_lines.py:68-70
- §3.7 — insert — ambiguity — kit order's `labor_minutes_actual` stays null until completion; job completion retains `board_stock_id` for settlement pricing — routes/kit_orders.py:75, routes/jobs.py:288
- §3.8 — insert — ambiguity — invoice `lines` fixed order: PRINT, BOARD, finish ops in COAT/FOIL/EMBOSS order, KITTING per COMPLETED kit order in creation order, MAKE_READY last; finalize's DRAFT-invoice state check precedes the job-COMPLETE check — calc.py:138-150,175-198, routes/invoices.py:79-84

### Mismatch revisions (revise)
- §3.1 — revise — mismatch — `brand_code` uniqueness is a plant convention only; the API does not enforce it (impl accepts duplicates) — routes/customers.py:24-33
- §3.5 — revise — mismatch — `press_code` uniqueness not enforced by the API — routes/presses.py:26-45
- §3.6 — revise — mismatch — `line_code` uniqueness not enforced by the API — routes/finishing_lines.py:27-46
- §5 — revise — mismatch — catalogue claimed to enumerate every error identifier but omitted `ERR_INTERNAL`, which the impl's catch-all handler emits at HTTP 500; row added — errors.py:51, app.py:44-47

**Cross-check notes**: Everything else in the impl (validation pipeline ordering, cascade levels, nesting/spoilage/yield formulas, tier pricing, per-line half-up rounding, window overlap semantics, kit allocation math, audit verdict thresholds, invoice settlement order-of-operations, all role assignments, all list filters) was already uniquely pinned by the PRD and left untouched.
