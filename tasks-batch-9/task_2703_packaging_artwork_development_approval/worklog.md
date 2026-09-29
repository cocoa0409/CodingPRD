# Worklog — task_2703_packaging_artwork_development_approval

## Step 1: Create task directory — 2026-09-04T08:54:03.312Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2703_packaging_artwork_development_approval` and `.../workspace` (pre-assigned path; no index auto-allocation performed).

## Step 2: Scaffold package generated — 2026-09-04

- `SCAFFOLD.yaml` (§1.0–§1.7): 12 entities, 10 state machines, 2 concurrency rules, 9 calculations, 56 validations, 55 endpoints, 56 errors, 7 roles. Contains neither `scaffold_difficulty_design` nor `scaffold_corner_design`.
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (§1.8): 9 rule ids x 2 instances = 18 instances.
- `SCAFFOLD_CORNER_DESIGN.yaml` (§1.9): 9-section breadth walk, 78 instances (59 with `test_recipe`, 19 `excluded_because` stubs).
- `scaffold_lint.py`: VERDICT: clean lint (1538 calls scanned). Coverage audit: 56/56 error ids asserted, 55/55 endpoints exercised.

## Step 2 (verbatim subagent summary) — 2026-09-04T11:06:00.000Z

The task-2703 scaffold package is complete and lint-clean.

Files
- `SCAFFOLD.yaml` — 3013 lines
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 3342 lines (single top-level key `scaffold_difficulty_design`)
- `SCAFFOLD_CORNER_DESIGN.yaml` — 9046 lines (single top-level key `scaffold_corner_design`)

`SCAFFOLD.yaml` top-level keys are exactly `scenario, domain_name, api_prefix, complexity_profile, response_envelope, entities, state_machines, concurrency_rules, calculations, validations, endpoints, errors, roles` — neither design key is present. All three files parse under PyYAML and end on a complete structural boundary.

§1.0–§1.7 counts: 12 entities, 10 state machines, 2 concurrency rules (`version-create-stale-asset`, `recovery-claim-stale-escape`), 9 calculations, 56 validations (priority ladder 1–56), 55 endpoints, 56 errors, 7 roles (`api_prefix: ""`, clock via `POST /_clock/set_current_utc`, `role_model: segregation_of_duties`, `consistency_model: immediate`, layers `optimistic_concurrency / cascading_side_effects / dual_variant_calculation / version_pinning_on_approval`).

§1.8 — 9 rule ids x 2 instances = 18: `dual_variant_calc`, `combinatorial_formula`, `non_linear_state_machine`, `transitive_cascade`, `priority_pair_validation_conflict`, `boundary_precision_check`, `cross_entity_state_dependency`, `resource_temporal_overlap`, `compensating_invariant`.

§1.9 — 78 instances across all nine guide sections: entities 12, state_machines 18, calculations 13, validations 13, endpoints 7, errors 3, rbac 6, cross_cutting_complexity_layers 5, consistency_model 1. 59 carry a `test_recipe`; 19 are `excluded_because` stubs, every citation resolving to a real §1.8 instance name. No duplicate instance name within or across the two design files.

Lint (verbatim):
```
Coverage
  §1.5 endpoints declared:    55
  §1.1 entities declared:     12
  §1.8 instances scanned:     18
  §1.9 instances scanned:     59
  Calls scanned (§1.8+§1.9):  1538

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

Coverage audits: error ids asserted by name 56/56; endpoints exercised by at least one `call:` 55/55; grounds resolver over both design files — zero unresolved, zero unknown-shape references. Hard constraint honoured: no sibling `tasks/task_*/` artifact was listed, read, or grepped.

Orchestrator verification: all three files present; `workspace/` survived Step 2 intact.

## Step 3: Copy shared files — 2026-09-04T11:07:03.708Z

Copied `./INSTRUCTION.md` → `tasks/task_2703_packaging_artwork_development_approval/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-04T11:22:00.000Z

Verbatim subagent summary:

All verifications pass on the final file.

Deliverable: `workspace/PRD.md` — 411 lines / 98,336 bytes, built incrementally (1 `Write` + 1 verbatim file-concat + heredoc appends), ends cleanly at the last row of the §5 table (`| \`ERR_RECOVERY_EXCEEDS_LIABILITY_CAP\` | 422 |`), no audit footer. Both `SCAFFOLD_DIFFICULTY_DESIGN.yaml` and `SCAFFOLD_CORNER_DESIGN.yaml` were never opened, grepped, or referenced. No sibling task under `tasks/` was read.

Section list (25 headings): §1 Introduction; §2 Global Specifications & System-Wide Principles (2.1 User Identity and RBAC, 2.2 API Response Structure (verbatim, confirmed byte-identical), 2.3 Pagination and List Ordering, 2.4 Resource Identity, Audit Fields and the Logical Clock, 2.5 Path Resolution and Reference Existence, 2.6 Optimistic Concurrency on Parent Records, 2.7 Rejection Precedence, 2.8 Money, Units, Rounding and Precision, 2.9 Cascade Discipline, Conserved Ledgers and Compensating Actions, 2.10 Controlled Vocabularies); §3 Business Logic & Workflows (3.1 Briefing the Pack, 3.2 Marketing Claim Library and Time-Bounded Legal Clearance, 3.3 Market Variants and the Revision Chain, 3.4 Mandatory Element Verification and the Compliance Score, 3.5 Routing for Review: Stages, Disciplines, Segregation of Duties, 3.6 Print Vendors and the Three Dimensions of a Proof, 3.7 Plate Ordering, the Plate Budget, and Release to Print, 3.8 Obsolescence Management and Inventory Runout Coordination, 3.9 Error Escape Investigation, Cost Recovery and Vendor Standing); §4 Endpoint Definitions (55-row table, exactly 4 columns); §5 Error Code Catalogue (56-row table, exactly 2 columns).

Hard Contract 1 — Field-Name Coverage: PASS. entities[].fields 151/151; endpoints[].input write bodies 78/78; GET query params 28/28; nested object keys 33/33. Strict whole-backtick-token match.

Hard Contract 2 — Rule Coverage: PASS. All 56 validations with error ids; priority ladder rendered as explicit six-band ladder in §2.7 plus operation-local re-statements at submit (§3.5) and plate-order/release (§3.7). Both concurrency_rules in §2.6 with write endpoint, expected-version field, error id, 412. All transitions across the 10 state machines with preconditions and side effects. All 8 calculations with every constant transcribed, incl. both dual-variant pairs (PROVISIONAL/FINAL, FORWARD_LOOKING/CHRONOLOGICAL). All endpoint side_effects, field defaults, and the full cascade set. Error statuses 56/56 match.

Hard Contract 3 — §3 Path Purity: PASS. 954 backtick tokens scanned in §3: 0 leading-slash paths, 0 bare HTTP-method tokens, 0 method+path tokens.

Coverage counts: endpoints 55/55 present in §4; errors 56/56 in §5 with correct status and 56/56 referenced in §2/§3 prose.

Late refinements: §1 entity count corrected to "a dozen linked record types"; §2.10 gained an explicit `ERR_INVALID_REQUEST` schema-violation paragraph enumerating conditionally-required-field cases.

Orchestrator truncation check (per known generator failure): `tail -c 800` confirms PRD.md ends at the final row of the §5 error table — a real section boundary, not mid-sentence. No regeneration needed.

## Step 5: Generate unit tests — 2026-09-04T13:12:00.000Z

Verbatim subagent summary:

All work is complete. Final state verified: 100 tests, full design coverage, everything compiles and imports.

Files written (all at the TASK ROOT, nothing under `workspace/`):
`test_helpers/` — 2675 lines: `__init__.py` 42, `api_client.py` 231 (56 methods), `api_errors.py` 126, `assertions.py` 316, `constants.py` 137, `factories.py` 417, `fixtures.py` 805, `test_users.py` 89, `types.py` 512
`test_suite/` — 6539 lines: `conftest.py` 67; queue A: `test_01` 217, `test_02` 182, `test_03` 202, `test_04` 191, `test_05` 170, `test_06` 196, `test_07` 166, `test_08` 247, `test_09` 202; queue B: `test_10_corner_entities` 671, `test_11_corner_state_machines` 609, `test_12_corner_calculations` 406, `test_13_corner_validations` 939, `test_14_corner_endpoints` 618, `test_15_corner_errors` 297, `test_16_corner_rbac` 542, `test_17_corner_complexity_layers` 386, `test_18_corner_consistency` 231

Tests per queue:
- Queue A (Difficulty, §1.8): 40 tests, 18/18 instances, every instance carrying >=2 tests, no dangling tags.
- Queue B (Corner, §1.9): 60 tests, 59/59 non-stub instances — entities 12/12, state_machines 10/10, calculations 7/7, validations 11/11, endpoints 6/6, errors 3/3, rbac 6/6, cross_cutting_complexity_layers 3/3, consistency_model 1/1. All 19 `excluded_because:` stubs left untranslated (tracker: `TAGGED STUBS: []`).
- 100 `def test_` and exactly 100 `Design:` lines — one tag per test, none dual-tagged or dangling. No `skip`/`xfail` anywhere.
- `python3 -m py_compile` clean on all 28 files; `importlib` sweep with `PYTHONPATH=.` imports all 27 modules; AST import-hygiene clean on every file.

Instances skipped: None. Every non-stub instance in both indices passed the two-condition PRD filter and was translated. Individual assertions dropped where PRD does not uniquely derive the design's claim:
- `escape_action_endpoints…`: design asserts `performance_penalty_points` stays null on a `WRITTEN_OFF` settlement; §3.9 only says "no scorecard penalty is computed", which does not distinguish null from 0. Asserted the unchanged vendor score and ledger instead.
- `brief_asset_count…`: dropped the claim that the brief's own `version` is untouched by child creates; §3.3 states only that the create "recomputes the parent brief's `asset_count`".
- `submit_reads_three_different_facts…`: dropped `usage_count == 1` for only the live claim; §2.9 makes it 1 for all four.

Design-yaml vs PRD conflicts (PRD followed in every case):
- `ERR_BRIEF_NOT_APPROVED` is 422 in the yaml, 409 in §5.
- Illegal enums corrected: `OFFSET_LITHO`→`OFFSET`, `"g"`/`"oz"`→`G`/`OZ`, `ALLERGEN_STATEMENT_OMITTED`→`WRONG_ALLERGEN`, `ARTWORK_CORRECTION`→`ERROR_CORRECTION`, claim_type `CONTENT`→`FREE_FROM`.
- `expedite_surcharge_cents` is not a PRD field; used `expedite_fee_cents`.
- Undecided tasks are `decision == "PENDING"` per §3.5, not null as the yaml asserts.
- `ERR_CLAIM_MARKET_MISMATCH` is checked only at submit (§3.5), not at version create — split into two tests.
- Zero-stock runout: `trailing_avg_usage_qty` is null while `depletion_records` is empty (§3.8), not 0.
- One instance's stated 100.0 compliance score is 97.5 under its own two-market brief (2.5 market-breadth penalty).
- `patch_of_a_revision_requested_version…` asks for `REVISION_REQUESTED` with a live FAIL row, which §3.5 makes unreachable (submission is blocked by `ERR_MANDATORY_ELEMENT_FAILED`); reached the state by waiving first, so the frozen figures are 87.5 / 0 failed / 1 waived.

Orchestrator verification: `test_helpers/` and `test_suite/` are at the task root (not under `workspace/`); 19 test files, 100 `def test_` functions.

## Step 6: Generate implementation — 2026-09-04T13:12:00.000Z

Verbatim subagent summary:

Verification pass complete. The implementation compiles, boots from a fresh process, and I exercised every major cascade end-to-end.

Files written (all under `workspace/implementation/`): `app.py` 106, `core.py` 184, `errors.py` 86, `http_util.py` 341, `calc.py` 441, `serialize.py` 339, `cascade.py` 154, `routes/__init__.py` 0, `routes/briefs.py` 205, `routes/claims.py` 137, `routes/assets.py` 114, `routes/versions.py` 412, `routes/element_checks.py` 71, `routes/review.py` 194, `routes/printers.py` 274, `routes/plates.py` 150, `routes/runouts.py` 276, `routes/escapes.py` 295, `requirements.txt` 1, `start.sh` 11 (executable). Total 3791 lines. Storage is in-memory dicts only (12 collections in `core.Store`), zero seeded rows, no disk state.

Endpoints: 55 registered rules = 54 domain endpoints across 10 blueprints + `POST /_clock/set_current_utc`, exactly matching SCAFFOLD.yaml. 9 POSTs return 201; all others 200. `py_compile` clean on all 18 `.py` files; `__pycache__` removed afterwards.

Runtime verification (4 boots on ports 39417/39623/39771/39833/39907, each killed by its own pid; no broad pkill; all ports confirmed free). Confirmed live: envelope shape and `req_<20 alnum>` ids; 401 missing headers vs 403 role; logical clock default `2026-08-01T00:00:00Z` on `created_at`/`updated_at` with wall clock only in `api_request_timestamp`; `ERR_STALE_ASSET_VERSION` 412; element verification (score 96.0 → waiver halves a MINOR deduction to 2 → 98.0); submit ladder reporting `ERR_MANDATORY_ELEMENT_FAILED` 422 ahead of money rules; SoD (author) and discipline-binding `ERR_UNAUTHORIZED` and `ERR_ROUTE_STAGE_NOT_ACTIVE` in ladder order; the four-link approval cascade; proof three-dimension derivation with brand-critical tolerance tightening (2.0 → 1.5) and `PRESS_CHECK_REQUIRED` → `PRESS_CHECK_ATTENDED` → `PROOF_APPROVED`; release-to-print refused 422 before a proof exists; plate pricing (6 sets expedited = 103000 + 60000 setup + 40750 = 203750); runout projection 2026-08-29 vs extrapolated `actual_runout_date`, `ERR_DEPLETION_RECORD_OUT_OF_ORDER` 409, SCRAP pricing (144000 base, 5% tier → 151200) with obsolescence completion, then reversal unwinding exactly one step; escape recovery (MARKET fee 150000, provisional 640000, settled 690000, variance 50000) driving the probation cascade to `performance_score` exactly 70.0 which correctly stays `CERTIFIED`; `ERR_CLAIM_CLEARANCE_OVERLAP`, `ERR_PRINTER_IDENTITY_MISMATCH`, `ERR_PRESS_CHECK_OVERLAP` all fire. Zero tracebacks in any server log.

PRD ambiguities resolved by interpretation:
1. Existence-check order: §2.5 says path left-to-right then body; scaffold gives fixed per-collection priorities. Implemented path ids first, then body ids in the scaffold's collection order.
2. Timestamp source: all timestamps come from the logical clock, so equal-clock rows need a tiebreaker — added an internal monotonic `_seq` (stripped from every projection) for `created_at ASC` list ordering.
3. Version-increment granularity: `touch()` registers rows per-request so an entity hit by both a direct mutation and a cascade link increments `version` exactly once.
4. Ledgers are computed, not stored: the four conserved ledgers and three counters are recomputed as sums/counts at serialization time, while the owning entity's `version` is still bumped wherever the PRD says it is touched.
5. `ERR_UNAUTHORIZED` for discipline binding: followed §2.7's band ladder (discipline → SoD → schema → stage → already-decided).
6. Objects created directly in post-transition state: ReviewRoute created at `IN_PROGRESS` (`version` 1); zero-stock runout created at `RUNOUT_COMPLETE` (`version` 1).
7. `POST /artwork-versions/{id}/submit` returns 200 with the ArtworkVersion (per SCAFFOLD), not 201.
8. Press-check overlap: both requested and stored window widened by 120 minutes each side, so two bookings on one `(printer_id, press_line_code)` need >=240 minutes of raw separation.
9. Undefined element-check `detail` strings: chose `"OK"`, `"ELEMENT_ABSENT"`, `"{CODE}_SUBRULE_FAILED"`.
10. `printer_share_pct` out of 0.00–1.00 is `ERR_INVALID_REQUEST`; an in-range value inconsistent with `root_cause_party` is `ERR_SHARE_INCONSISTENT_WITH_PARTY`.
11. Settle ordering: for `SETTLED` the three required actuals are validated (`ERR_INVALID_REQUEST`) before the state check; `SETTLED` only from `RECOVERY_CLAIMED`, `WRITTEN_OFF` from `RECOVERY_CLAIMED` or `DISPUTED`.
12. Unspecified regexes: market `^[A-Z]{2}$`, language `^[a-z]{2,3}$`, claim code `^[A-Z0-9-]{3,40}$`, GTIN-14 exactly 14 digits. Unknown keys rejected at top level of a write body and inside a `records` entry, tolerated inside `mandatory_elements` sub-objects.
13. Clock endpoint returns `data: {}` because the scaffold declares `output: null`.

Orchestrator note: Steps 5 and 6 were launched concurrently in a single message, so the implementation generator could not see `test_suite/` (it did not exist at its spawn time).

## Step 7: Run tests and iterate — 2026-09-04T13:22:00.000Z

Verbatim subagent summary:

All 8 rounds of the second sweep are green at 100/100.

**Iterations run:** 2 (iteration 1 = baseline diagnosis at 87/100 in all 8 rounds; iteration 2 = clean).

**Tests deleted:** none in full. Four assertions were removed under STEP 1c (partial coverage / COMPUTED-FIELD SILENCE), all four asserting `performance_penalty_points` on the `ErrorEscape` response body:
- `test_suite/test_04_approval_and_settlement_cascades.py` — `test_penalty_points_drive_the_score_below_the_probation_floor`
- `test_suite/test_12_corner_calculations.py` — `test_a_score_of_exactly_seventy_leaves_the_vendor_certified`
- `test_suite/test_13_corner_validations.py` — two settlement probes

PRD §3.9 names `performance_penalty_points` only as an intermediate inside the scorecard formula ("`performance_penalty_points` is computed and subtracted from the vendor's `performance_score`"); the sentence enumerating what settlement stores on the escape ("The escape stores its three actuals, sets `resolution`…, stamps `settled_at`") omits it, and §4's `GET /error-escapes/{id}` row lists only apportionment, both recovery variants, the variance and the cap flag. Each test still verifies the penalty arithmetic through the vendor's resulting `performance_score`, so no PRD coverage was lost.

One further probe was removed under STEP 1b (unique derivability), in `test_suite/test_11_corner_state_machines.py` `test_the_original_decider_trips_segregation_before_already_decided`: the original decider re-firing the *same* task was asserted to yield `ERR_SEGREGATION_OF_DUTIES`. PRD §3.5 scopes the check to "an identifier already recorded as `decided_by_user_id` on **any other task** of the same pass", which excludes the task being decided. The test was also internally inconsistent with the catalogue (it expected HTTP 409 for a code catalogued as 403). Replaced with a same-user probe asserting `ERR_TASK_ALREADY_DECIDED`, keeping the repeat-call coverage.

**Fixes applied to `test_helpers/`:** none. No fixture, factory or header helper was at fault.

**Fixes applied to `implementation/`:** none. Every failure traced to a test-side assertion contradicting PRD prose.

**Other `test_suite/` fixes (STEP 2 — test made more faithful to PRD):**
- `test_08_temporal_overlap_windows.py` (4 tests), `test_10_corner_entities.py`, `test_13_corner_validations.py` — nine assertions expected operator-supplied `*_utc` instants echoed verbatim without fractional digits. PRD §2.4 states unconditionally "Timestamps are rendered as ISO 8601 UTC with three fractional digits", and §2.4 itself classes `*_utc` clearance and press-check windows as timestamps. Expectations updated to the three-fractional-digit rendering (added `INCUMBENT_START_RENDERED` / `INCUMBENT_END_RENDERED` in test_08).
- `test_06_tolerance_and_trailing_average_boundaries.py::test_the_tightening_is_what_fails_a_measurement_of_one_five_one` — asserted `proof_state == "PROOF_IN_REVIEW"` after a `COLOR_FAIL`. PRD §3.6: "If `color_status` is `COLOR_FAIL` … the proof is `PROOF_REJECTED` — and this holds even while another dimension is still pending". Corrected to `PROOF_REJECTED`.
- `test_10_corner_entities.py::test_shape_violations_are_reported_before_any_reference_is_resolved` — the runout probe passed an asset id as `obsolete_version_id`, so the PRD-correct answer was `ERR_ARTWORK_VERSION_NOT_FOUND`: §2.7 resolves existence in band two, ahead of `ERR_INVALID_REQUEST` in band four. The probe now names a version that resolves, isolating the negative `on_hand_qty` as the sole violation so the `ERR_INVALID_REQUEST` expectation holds (and still outranks the band-six DRAFT-state check).

**Final per-round figures:** rounds 1–8 all 100/100 passed.

Orchestrator verification: 8 `results.{1..8}.json` files present under `workspace/implementation/`, each parsed independently — `passed=100 total=100 failed=0` in all eight. Sweep artifacts confirmed on disk, not just claimed.

Orchestrator decision on Step 8: Step 7 applied **0 `implementation/` fixes**, but it was NOT a zero-iteration exit — 2 iterations ran, with 5 assertion-level `test_suite/` changes and 5 test-side fidelity fixes. The skill's skip condition requires 0 deletions AND 0 test_suite fixes AND 0 test_helpers fixes AND 0 implementation fixes. That condition is not met, so Step 8 runs. Its `<step_7_diff>` items are all PRD-silence/ambiguity signals (COMPUTED-FIELD SILENCE on `performance_penalty_points`, the same-task segregation scoping, the fractional-digit timestamp rendering, the COLOR_FAIL immediate-rejection branch, the existence-vs-schema band ordering) — exactly the sites Step 8 exists to pin, even though the implementation itself needed no change.

## Step 8: Finalize PRD — 2026-09-04T13:33:00.000Z

Verbatim subagent summary:

Done. Both files are 411 lines; PRD_FINALIZED.md ends at the same final §5 table row (`ERR_RECOVERY_EXCEEDS_LIABILITY_CAP | 422`).

Line counts: `PRD.md` 411 lines / 98,336 bytes; `PRD_FINALIZED.md` 411 lines / 98,966 bytes. Line delta 0% (2 lines revised in place: 86 and 284); byte delta +630 (+0.64%).

Changes:
- §2.4 — revise — timestamp rendering now explicitly covers operator-supplied `*_utc` instants (normalised to UTC and re-rendered with three fractional digits rather than echoed verbatim), with an explicit carve-out that calendar-date fields keep `YYYY-MM-DD` — `implementation/core.py:66` (`fmt_dt`), applied at `routes/claims.py:128-129`, `routes/printers.py:266-267`, `routes/runouts.py:89,187`.
- §3.9 — revise — `performance_penalty_points` marked a transient intermediate, persisted on neither the escape nor the vendor and absent from every response body — `implementation/cascade.py:134-147` (local variable, discarded), `implementation/serialize.py:309-339` (`escape_json` omits it), `serialize.py:213-227` (`printer_json` omits it).

Per-edit pre-edit search log:

Edit 1 — §2.4 timestamp rendering
- (a) Subject: how every `*_at`/`*_utc`/date-valued field is rendered in responses, especially operator-supplied instants.
- (b) Paths enumerated: `core.py` `fmt_dt`/`now_iso`/`wall_iso`/`date_str`/`parse_dt`; `http_util.py:278` `need_datetime`; every `_utc` write site (`grep -rn "_utc" routes/ calc.py cascade.py`) — `routes/claims.py:128-129` (`cleared_from_utc`/`cleared_until_utc` via `fmt_dt`), `routes/printers.py:266-267` (`press_check_start_utc`/`press_check_end_utc` via `fmt_dt`), `routes/runouts.py:89` (`runout_start_utc`) and `:187` (nested `depletion_records[].week_start_utc`), `cascade.py:64` (`pinned_claim_snapshot[].cleared_until_utc`, copied from the already-rendered claim value); all server-stamped `*_at` (`approved_at`, `released_at`, `obsoleted_at`, `decided_at`, `completed_at`, `cancelled_at`, `settled_at`, `created_at`, `updated_at`) via `now_iso`; `meta.api_request_timestamp` via `wall_iso`; date-valued `projected_runout_date`/`actual_runout_date` via `date_str` (`calc.py`, `serialize.py:291-292`); `app.py:58-67` clock `to_iso8601` (parsed, never echoed — response `data` is `{}`).
- (c) Adjustment: scoped the universal claim to `*_at`/`*_utc` instants and added the explicit parenthetical excluding calendar-date fields, because `projected_runout_date`/`actual_runout_date` render as `YYYY-MM-DD` and a blanket "all date/time fields" sentence would have contradicted them. Also said "normalised to UTC and re-rendered" rather than "reformatted", since `parse_dt` converts non-UTC offsets via `astimezone(timezone.utc)`.

Edit 2 — §3.9 `performance_penalty_points`
- (a) Subject: whether the settlement scorecard penalty figure is stored/exposed anywhere.
- (b) Paths enumerated: `grep -rn "performance_penalty_points"` across `implementation/` (zero hits — only `test_helpers/types.py:506` and a test docstring); `cascade.py:134-147` `apply_settlement_penalty` (penalty is a local, returned but the return value is unused at `routes/escapes.py:293`); `calc.performance_penalty` / `calc.apply_penalty`; `routes/escapes.py:223-294` settle (writes only the three actuals, `final_recovery_cents`, `recovery_variance_cents`, `resolution`, `settled_at`, `state`, `settlement_note`); `serialize.escape_json` and `serialize.printer_json` field lists; `cascade.flag_proofs_for_recheck` (touches proofs only).
- (c) Adjustment: wrote "persisted on neither the escape nor the vendor" rather than only "not stored on the escape", since the impl also does not persist it on the `Printer` row (only the reduced `performance_score` is stored). Left the existing penalty arithmetic prose verbatim.

Items deliberately not patched (PRD already uniquely determines the impl behaviour; test-side bugs only):
- Segregation of duties excluding the task being decided — §3.5 already says "any other task of the same pass"; `routes/review.py:121-128` skips `sibling["id"] == task["id"]`, and §5 already fixes `ERR_SEGREGATION_OF_DUTIES` at 403 / `ERR_TASK_ALREADY_DECIDED` at 409.
- `proof_state` = `PROOF_REJECTED` on `COLOR_FAIL` while another dimension pends — §3.6 states it verbatim.
- `ERR_ARTWORK_VERSION_NOT_FOUND` outranking `ERR_INVALID_REQUEST`, and `ERR_INVALID_REQUEST` outranking the `OBSOLETE_PENDING` state check — §2.7 bands 2/4/6 already fix this, matching `routes/runouts.py:47-79`.

Orchestrator verification: `PRD_FINALIZED.md` exists, is NOT byte-identical to `PRD.md` (98,966 vs 98,336 bytes), and ends at the same real section boundary (final §5 error-table row).

## Step 9: Complete PRD — 2026-09-04T14:20:00.000Z

Orchestrator decision: Step 9 was run as **three sequential, impl-module-partitioned passes** over one shared `workspace/PRD_COMPLETED.md`, rather than one subagent, because an exhaustive walk of 3791 lines of implementation against a 114KB PRD does not fit one context and a single-pass subagent tends to produce a byte-identical file (the scan never actually happening). Pass 1 performed the `cp PRD_FINALIZED.md PRD_COMPLETED.md`; passes 2 and 3 were explicitly forbidden from copying and edited in place additively.

Partition: pass 1 = `app.py`, `core.py`, `errors.py`, `http_util.py`, `serialize.py`, `cascade.py`, `calc.py`; pass 2 = `routes/briefs.py`, `claims.py`, `assets.py`, `versions.py`, `element_checks.py`; pass 3 = `routes/review.py`, `printers.py`, `plates.py`, `runouts.py`, `escapes.py`. Each pass was told what earlier passes had already pinned so it would not re-litigate.

### Pass 1 (cross-cutting modules) — verbatim summary

File stats: `PRD_FINALIZED.md` 411 lines / 98,966 chars (source); `PRD_COMPLETED.md` 411 lines / 103,472 chars → +4,506 chars, 16 lines revised, no new lines/paragraphs/sections, not byte-identical, still ends at `| ERR_RECOVERY_EXCEEDS_LIABILITY_CAP | 422 |`. Both Step 8 edits verified intact.

Counts: 14 ambiguity-pins, 2 mismatch-revisions (16 edits total).

Changes:
- §2.1 — revise — ambiguity — a present-but-blank/whitespace-only `X-User-ID` counts as absent for `ERR_MISSING_AUTH_HEADERS` — `http_util.py:59`
- §2.2 — revise — ambiguity — `api_request_id` is `req_` + exactly 20 chars from `A`–`Z`/`0`–`9`, minted for every response incl. errors — `core.py:60-62`
- §2.2 — revise — ambiguity — `api_request_timestamp` is read from real wall-clock time, the sole exception to the §2.4 logical clock — `http_util.py:25`, `core.py:109`
- §2.3 — revise — ambiguity — a non-integer `limit`/`offset` is `ERR_INVALID_REQUEST`; an empty string for either is treated as omission and takes the default — `http_util.py:67-97`
- §2.3 — insert — ambiguity — every ordering is made total by breaking ties on service-creation sequence; the descending brief list reverses the tie-break too — `core.py:183`, `routes/*.py` sort keys
- §2.4 — insert — ambiguity — supplied instants: non-zero UTC offsets converted, zone-less instants read as already UTC — `core.py:82-97`
- §2.4 — insert — ambiguity — `version` advances at most once per request, not per write; a row created and further mutated in the same request is returned at `version` 1 — `core.py:153-176`, `routes/runouts.py:105-113,240`
- §2.8 — revise — ambiguity — scores render keeping their one decimal place (`100.0`), while `deduction_points` renders as a bare integer when it has no fractional part — `calc.py:205-216`, `serialize.py:142,167,221`
- §2.10 — revise — ambiguity — explicit `null` is indistinguishable from absent; an absent body is read as `{}`; a present non-object body is `ERR_INVALID_REQUEST` — `http_util.py:134-148,167+`
- §3.1 — revise — ambiguity — language subtags are two or three lowercase letters exactly — `calc.py:90`
- §3.2 — revise — **mismatch** — `claim_code` charset is uppercase letters, digits and dash (PRD said "uppercase-and-dash") — `calc.py:91`
- §3.4 — revise — ambiguity — sub-rule failure `detail` is the element code + literal `_SUBRULE_FAILED` — `calc.py:279`
- §3.5 — revise — ambiguity — `submit_note` is stored on both the version and the routing pass; `verification_note`/`revise_note`/`release_note` persist on the version and are returned on every read — `serialize.py:145-148,186`, `routes/versions.py:240,269,347,371,410`
- §3.5 — revise — ambiguity — `stage_plan` is an array of three objects in ascending `stage_no`, each with exactly `stage_no`, `mode`, `disciplines` — `calc.py:147-151`, `serialize.py:183`
- §3.8 — revise — **mismatch** — obsolescence completion is guarded per row: an already-`OBSOLETE` version or an asset no longer `SUPERSEDE_PENDING` is left untouched and unversioned; asset `version` moves only if the request wrote to it, never by 2 — `cascade.py:94-105`, `routes/runouts.py:240-243`
- §3.8 — revise — ambiguity — the same guard on the reversal step (`OBSOLETE → OBSOLETE_PENDING`, `SUPERSEDED → SUPERSEDE_PENDING`) — `cascade.py:108-119`
- §5 — insert — ambiguity — unrouted path → `ERR_INVALID_REQUEST` at HTTP 404, unsupported method → `ERR_INVALID_REQUEST` at HTTP 405 (outside the table's 400 mapping, no auth check); trailing slash accepted — `app.py:26,84-91`

Already pinned, left alone: full error catalogue (`errors.py` ERROR_HTTP matches all 56 §5 rows exactly); every `calc.py` constant and formula (severity weights 25/10/4 and 0.5 waiver factor, scheme factors 1.00/1.10/1.05, market 2.5 / language 1.5 penalties with 2-language free count, 70.0 floor and 0–100 clamp, revision cap 3, ΔE tolerance table + 0.5 brand-critical tightening, 120-minute press-check buffer, plate ladder 18000/15500/13000 with 4/8 bands, 60000/90000 setup, 25% expedite, `STANDARD_UNIT_COST_CENTS` 42/9/15/120, 7¢ scrap handling, 18¢ rework, changeover tiers 5/8/12% with exclusive ceilings, investigation fee 60000/150000, 2.0 points per 1000 units + stage penalties, 40.0 cap, strict `< 70.0` probation, 7-day weeks, 3-record trailing window floored at 1, `derive_proof_state`, per-line rounding in `recovery_sum`); conserved ledgers and counters (derived at read time — unobservable); `paginate` meta and `has_more`; envelope shapes; 201-on-create; clock endpoint's empty-object 200. `http_util.load()`'s non-string-id branch is unreachable — deliberately NOT pinned as a 404. Gap handed to pass 3: `routes/review.py:178-183` `CONDITIONAL`-plus-stage-advance appends to `open_condition_codes` without touching the version.

### Pass 2 (brief / claim / asset / version / element-check routes) — verbatim summary

Char count: 103,472 → 107,364 (+3,892). Still 411 lines, no paragraphs or sections added (29 modified lines, 0 net line changes). Pass 1's edits verified present (blank-`X-User-ID`-as-absent, `100.0` scorecard rendering, language-subtag regex) and Step 8's `performance_penalty_points` clause intact. File still ends at the final §5 row.

Counts: 15 changes — 13 ambiguity-pins, 2 mismatch-revisions.
- §2.3 — insert — ambiguity — list-filter validation depth: FK filters existence-checked, integer-valued filters 400 on non-integer, closed-vocabulary filters not validated at all (undeclared value → empty page), empty-string filter == omitted — `routes/element_checks.py:36-41`, `routes/briefs.py:126-129`, `http_util.py:93-97`
- §3.1 — revise — ambiguity — `structural_spec`: all four keys required; `l`/`w`/`h` checked only as integers, so zero/negative accepted — `routes/briefs.py:28-43`
- §3.1 — insert — ambiguity — `us_value` need only be a number with no positivity bound; both quantities may be fractional; extra keys inside nested objects ignored (unknown-field rule is top-level only) — `routes/briefs.py:48-62`, `http_util.py:142-144`
- §3.1 — revise — ambiguity — brief PATCH: explicit `null` on an editable field is `ERR_INVALID_REQUEST`; `sku_code`/`regulatory_scheme` are unknown fields; a field-less PATCH is accepted and still bumps `version` — `routes/briefs.py:138-171`
- §3.1 — insert — ambiguity — the two approval-only preconditions raise `ERR_INVALID_REQUEST` after the brief-state check (unreachable in practice) — `routes/briefs.py:193-198`
- §3.2 — insert — ambiguity — a `CLEARED` decision on a claim not in `DRAFT` is `ERR_CLAIM_STATE_INVALID` — `routes/claims.py:104-105`
- §3.2 — insert — ambiguity — fields belonging to the other decision are neither validated nor stored — `routes/claims.py:80-100`
- §3.3 — insert — ambiguity — asset `component_type`/`substrate_class` are never compared with the brief's `structural_spec`; only market/language coverage is checked — `routes/assets.py:52-70`
- §3.3 — insert — ambiguity — `expected_artwork_asset_version` is an integer ≥ 0; version creation is admissible whatever the asset's `obsolescence_state` and whatever state the predecessor stands in — `routes/versions.py:77,86-97`
- §3.3 — revise — **mismatch** — version PATCH: field-less edit accepted; explicit `null` on `mandatory_elements`/`reason_for_change_code`/`change_description` is `ERR_INVALID_REQUEST`, while `null` `claim_ids` resets the array to empty — `routes/versions.py:161-174,40-41`
- §3.4 — insert — ambiguity — `mandatory_elements` may be `{}`; sub-objects for non-required elements and unrecognised keys are ignored — `routes/versions.py:80`, `calc.py:268-279`
- §3.4 — revise — **mismatch** — a sub-object present but not a JSON object counts as `ELEMENT_ABSENT`, not a schema error — `calc.py:272-276`
- §3.4 — insert — ambiguity — re-verification from `APPROVED` leaves `state` at `APPROVED` and never clears `open_condition_codes` — `routes/versions.py:241-245`
- §3.4 — insert — ambiguity — each run overwrites `verification_note`, so a re-run that omits it returns the field to null — `routes/versions.py:240`
- §3.4 — insert — ambiguity — `waiver_justification` must be non-empty after trimming; a waiver is admissible in any version/asset state and changes neither — `routes/element_checks.py:52-54,63-70`

Judged already pinned: the submit-precondition ladder and error codes; the release-to-print four-check order; element order, seven sub-rules, severity map, deduction weights and four-input score arithmetic; route/task creation shape and the immediate `PENDING → IN_PROGRESS`; clearance half-open overlap and withdrawal retaining bounds; `version_counter`/`version_no` sequencing; asset creation defaults and duplicate-variant-before-coverage ordering; revise-cycle cap at 3; all documented list filters and orderings.

### Pass 3 (review / printer / plate / runout / escape routes) — verbatim summary

`PRD_COMPLETED.md`: 107,364 → 114,381 chars (411 lines, unchanged — every change an in-paragraph insert or revision). Still ends at the final `ERR_RECOVERY_EXCEEDS_LIABILITY_CAP | 422` row. Spot-checked four earlier edits still present.

Counts: 17 ambiguity-pins, 3 mismatch-revisions (19 `Edit` calls; one edit carried two behaviors).
- §3.5 — insert — ambiguity — the discipline-binding `ERR_UNAUTHORIZED` is a first-band rejection evaluated as soon as the task resolves, ahead of SoD, schema validation and every state precondition — `routes/review.py:111-116`
- §3.5 — insert — ambiguity — "non-empty" means non-blank (whitespace-only == empty; non-string rejected), governing `cancel_reason`, `reversal_reason`, `dispute_reason`, `investigation_note` too — `routes/review.py:134-141`
- §3.5 — revise — ambiguity — a `CONDITIONAL` verdict also stores the optional `comment`; a `condition_code` sent with `APPROVED`/`REJECTED` is accepted then discarded — `routes/review.py:157-163`
- §3.5 — insert — ambiguity — the pass's `version` advances by exactly 1 on every accepted decision, including one that only recomputes `conditional_count` — `routes/review.py:167-170,190`
- §3.5 — revise — **mismatch** — the handed-over gap: a `CONDITIONAL` that resolves its stage `APPROVED` while `current_stage_no` < 3 appends to `open_condition_codes` without refreshing the version's `updated_at` or `version`; only the stage-3 resolving `CONDITIONAL` lifts it — `routes/review.py:164,179-192`
- §3.6 — revise — ambiguity — printer `name` uniqueness is exact string comparison (case- and whitespace-sensitive) — `routes/printers.py:47-49`
- §3.6 — insert — ambiguity — `measured_delta_e_max` must be ≥ 0, no upper bound, stored as supplied and never re-rounded; it and `effective_tolerance` render as decimals keeping a zero fraction — `routes/printers.py:192-201`, `serialize.py:245-246`
- §3.6 — revise — **mismatch** — press-check collision requires raw endpoints separated by at least four hours (2 h per window), exactly four permitted — `routes/printers.py:243-263`
- §3.6 — insert — ambiguity — `attended_by_user_id` is any non-empty string stored verbatim with no existence check; a second call on a `PRESS_CHECK_SCHEDULED` track is a full re-booking; the proof's own booking is excluded from the scan — `routes/printers.py:235-272`
- §3.6 — insert — ambiguity — boolean filter shape (`requires_recheck`, `auto_cancelled`): `true/false/1/0` case-insensitive and trimmed, anything else `ERR_INVALID_REQUEST` — `http_util.py:100-109`, `routes/printers.py:175`, `routes/plates.py:121`
- §3.8 — insert — ambiguity — `artwork_asset_id` and `obsolete_version_id` are resolved independently and never cross-checked; the asset the runout names governs pricing, both ledgers and obsolescence completion — `routes/runouts.py:47-72,212`
- §3.8 — insert — ambiguity — `records` has no max length; each entry must carry exactly `week_start_utc` and `units_consumed` (unknown keys rejected inside an entry, unlike §3.1's nested objects), `units_consumed` integer ≥ 0, all validated before the state check — `routes/runouts.py:150-167`
- §3.8 — insert — ambiguity — an append driving `remaining_qty` to 0 still leaves the runout `MONITORING` with a null `disposition` — `routes/runouts.py:189-190`
- §3.8 — insert — ambiguity — on a `RUNOUT` disposition the two unit counts are accepted and discarded with no validation — `routes/runouts.py:199-220`
- §3.8 — revise — **mismatch** — on a disposition reversal the asset's `version` always increments while the obsolete version's increments only if the unwind conditional fired; `remaining_qty`, `actual_runout_date`, `trailing_avg_usage_qty`, `projected_runout_date` are all left untouched — `routes/runouts.py:260-275`, `cascade.py:108-119`
- §3.9 — insert — ambiguity — an escape's `artwork_version_id` and `printer_id` are never cross-checked — `routes/escapes.py:36-58`
- §3.9 — insert — ambiguity — `printer_share_pct` must be a number in [0.00, 1.00] (`ERR_INVALID_REQUEST` ahead of the party-consistency check), compared numerically, echoed back as the supplied JSON number — `routes/escapes.py:130-150`, `serialize.py:322`
- §3.9 — insert — ambiguity — `dispute_reason` and `dispute_count` survive a revising apportionment unchanged — `routes/escapes.py:152-160`
- §3.9 — insert — ambiguity — `expected_error_escape_version` must be an integer ≥ 0; a negative/non-integer value is `ERR_INVALID_REQUEST` ahead of the staleness comparison — `routes/escapes.py:170`
- §3.9 — insert — ambiguity — a `WRITTEN_OFF` settlement accepts and discards the three actual amounts without validating them; all three stay null — `routes/escapes.py:227-253,282-286`

Judged already pinned: the §2.7 band ordering as it plays out in every pass-3 endpoint; the plate cost band ladder, setup thresholds and expedite surcharge; changeover tiers and exclusive ceilings; both runout projection variants and the trailing-average floor of 1; `derive_proof_state` and the `press_check_required` / `effective_tolerance` formulas; `proof_no` as a per-version count; the four-line recovery arithmetic with per-line rounding, provisional clamp and settlement cap refusal; the probation cascade; all list orderings and filter sets; every §5 status code.

### Step 9 aggregate

PRD.md 98,336 chars → PRD_FINALIZED.md 98,966 → PRD_COMPLETED.md **114,381** chars (411 lines throughout; every change an in-paragraph insert or revision, zero new sections). Total across the three passes: **44 ambiguity-pins + 7 mismatch-revisions = 51 edits**.

Orchestrator verification: `PRD_COMPLETED.md` exists, is NOT byte-identical to `PRD_FINALIZED.md` (114,381 vs 98,966), ends at the real final §5 error-table row, and the 8 sweep result files still read 100/100 in every round. Pipeline complete.
