# Worklog — task_2493_fit_guidance_return_reduction_program

## Step 1: Create task directory — 2026-09-03T01:02:56.527Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2493_fit_guidance_return_reduction_program/` and `.../workspace/` (pre-assigned path from the orchestrator invocation; no index auto-allocation performed, per instruction that 32 pipelines run concurrently on this host).

## Step 2: Generate scaffold — 2026-09-03T03:10:55.933Z

Verified by orchestrator before recording: SCAFFOLD.yaml = 2774 lines / 13 top-level keys with neither design key; SCAFFOLD_DIFFICULTY_DESIGN.yaml = 2090 lines / single key `scaffold_difficulty_design`; SCAFFOLD_CORNER_DESIGN.yaml = 4155 lines / single key `scaffold_corner_design`. All three parse as YAML. The difficulty instruction line ("Generate task harder than expert level!") was forwarded to this subagent only and will not be passed to Steps 4/5/6.

Subagent summary (verbatim):

All three scaffold artifacts for task 2493 are complete and validated.

## Files written

- `/home/ubuntu/github/CodingPRD/tasks/task_2493_fit_guidance_return_reduction_program/SCAFFOLD.yaml` — 2774 lines, 13 top-level keys (§1.0–§1.7). Contains neither `scaffold_difficulty_design` nor `scaffold_corner_design` (grep count 0).
- `.../SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 2090 lines, single top-level key `scaffold_difficulty_design` (§1.8).
- `.../SCAFFOLD_CORNER_DESIGN.yaml` — 4155 lines, single top-level key `scaffold_corner_design` (§1.9).

The hard constraint was honored: no sibling task directory was listed, globbed, grepped, or read at any point. Every read touched only the skill directory, `/tmp` scratch chunks, and task_2493's own directory.

## Lint verdict (verbatim)

```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           tasks/task_2493_fit_guidance_return_reduction_program/SCAFFOLD.yaml
  Difficulty design:  tasks/task_2493_fit_guidance_return_reduction_program/SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      tasks/task_2493_fit_guidance_return_reduction_program/SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    52
  §1.1 entities declared:     13
  §1.8 instances scanned:     18
  §1.9 instances scanned:     54
  Calls scanned (§1.8+§1.9):  789

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

Clean on first run; re-run clean after three self-found fixes (see below).

## Replay checks

**Call-by-call rule replay — pass.** Each of the 789 calls was walked against the §1.2/§1.3/§1.4/§1.6 rules it exercises. Mechanised evidence: 96 instance names unique across the union of both files; zero unbound `${…}` placeholders (every one is bound by an earlier `as`/`captures` in the same recipe); zero unbound assert variables; zero static OCC values (every `expected_*_version` is a `${var}` captured from a prior read); zero unresolvable `grounds` anchors (all resolve into §1.1–§1.6); a full enum-literal sweep of every payload field against its §1.1/§1.5 enum is clean apart from the one deliberately-invalid payload that an instance exists to reject. Validation-priority instances replay in declared priority order (12/23/27/30/31 chains land on the expected code, not a higher-priority one).

**End-state replay including side effects — pass.** All formula-derived literals were recomputed by hand rather than copied. Cost-ledger totals re-derived on `refund` (not `gross`), which is where PAYMENT_FEE_UNRECOVERED applies: FIT/RESELLABLE_A on 2295 → 795+558+34+0+67 = 1454; CHANGE_OF_MIND → 1330; EXPECTATION/RESELLABLE_B on 4590 → 795+682+184+551+133 = 2345; QUALITY → 795+1054+34+0+67−918 = 1032. Restocking fee is 0 at gross 2295 (below RESTOCK_TIER_1_CENTS 5000), so the RESTRICTED abuse multiplier is a verified no-op there and refunds stay positive. Vendor reliability decay replays 9700 → 5500 → 5200 → 4900 across 17 correction rounds spread over 6 auxiliary items (MAX_CORRECTION_ROUNDS caps one spec at 3), with 5500/5200 correctly still PROBATION so intermediate resubmits remain legal, and 4900 crossing to SUSPENDED. Strike aging replays exactly: 2026-07-10 minus 180 d = 2026-01-11, and strict `>` fails for `requested_at` 2026-01-10, so strikes 1 → 0 and status WATCH → CLEAR. Version-bump side effects (`pdp-enhancement` and `publish-guidance` both bumping `CatalogItem.version`) replay through the two 412 instances: stale 2 → 412 → retry with 3 → final version 4. Manual deployment termination replays the `window_end` rewrite to the clock instant plus a zero-width subsequent measurement window. Every recipe reproduces its state from an empty DB using only §1.5 endpoints, with the clock driven by `POST /_clock/set_current_utc` and no wall-clock waits.

## Quality + Diversity checklist

- **Completeness** — §1.0–§1.9 all present and populated; 52 endpoints, 13 entities, 46 error codes.
- **Difficulty audit** — all nine §0.5 rules × 2 instances = 18, each pair carrying a falsifiable `distinguishing_aspect` that names what the second instance breaks that the first does not.
- **§1.9 breadth census** — 9 sections, 78 instances: 54 real recipes + 24 `excluded_because:` stubs, each stub citing an existing `rule_id / instance_name` in the difficulty file. Per section (total/real): entities 12/11, state_machines 13/8, calculations 11/5, validations 15/13, endpoints 3/3, errors 11/5, rbac 5/5, cross_cutting 7/3, consistency_model 1/1.
- **Error triggerability** — all 46 declared error codes are triggered somewhere across §1.8+§1.9; uncovered set is empty.
- **Claim-type spread** — no section collapses onto a single claim type where the guide offers several: entities spans 10 distinct types, state_machines 9, calculations 6, cross_cutting 4, rbac 4.
- **Structured setup** — every instance carries a mandatory structured `setup_api_calls` with `call`/`payload`/`as` (+`as_user_id`/`captures`), placeholder closure holds, and every negative trigger captures `err_id: $.data.error_id`.

## Defects found and fixed during self-audit

1. YAML parse failure — unquoted JSONPaths containing `[` inside flow-style `captures: { … }` mappings (`$.data[5].component`, `$.data[5].amount_cents`, `$.data[0].signal_weight`); quoted in place.
2. Invalid enum literal `retire_reason_code: "SUPERSEDED_BY_STANDARD"` → `SUPERSEDED_BY_NEW_CHART`. This mattered because the bad enum would trip priority-5 ERR_INVALID_REQUEST and mask the instance's intended 409 ERR_INVALID_CHART_STATE.
3. Malformed fake UUIDs in the ten-way not-found sweep (non-hex suffixes) could be rejected as malformed input instead of resolving to 404; rewritten with hex-valid suffixes.

## Step 3: Copy shared files — 2026-09-03T03:11:20.000Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` → `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-03T03:27:42.433Z

Orchestrator truncation check (the known doc-generator failure mode): `workspace/PRD.md` is 448 lines and its tail is the final row of the §5 error table (`ERR_VENDOR_CORRECTION_BUDGET_EXHAUSTED | 402 Payment Required`) — a real section boundary, not mid-sentence. Independent cross-check against SCAFFOLD.yaml: all 46 declared error ids appear in the PRD (0 missing) and all 52 declared endpoint paths appear in the PRD (0 missing). Heading spine runs §1 → §2 (2.1–2.11) → §3 (3.1–3.9) → §4 → §5 with no gaps. No regeneration needed.

Subagent summary (verbatim):

PRD generation for task_2493 is complete.

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_2493_fit_guidance_return_reduction_program/workspace/PRD.md`

**Final line count: 448.** Last section heading: `## 5. Error Code Catalogue`. The file ends at a real section boundary — the final row of the §5 error table (`` `ERR_VENDOR_CORRECTION_BUDGET_EXHAUSTED` | 402 Payment Required ``), with no audit footer and no contract-report block.

**Structure written:** §1 Introduction; §2 with 11 subsections (2.1 RBAC/identity translation, 2.2 verbatim response structure, 2.3 pagination, 2.4 common resource properties, 2.5 logical clock, 2.6 arithmetic discipline, 2.7 OCC stale-version guards, 2.8 cascade discipline / two item axes, 2.9 the 31-rank validation ladder, 2.10 append-only cost ledger, 2.11 vendor standing); §3 with 9 workflow subsections (3.1 vendors & items, 3.2 spec verification, 3.3 charts & mappings, 3.4 PDP & guidance publication, 3.5 fit feedback, 3.6 fit recommendation, 3.7 shoppers/policy/purchases/opening a return, 3.8 coding/closing/reversing returns & shopper standing, 3.9 levers/measurement windows/ops-run checkpoint); §4 52-row endpoint table; §5 46-row error table.

The withheld files (`SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`) were never opened, grepped, or referenced.

**Hard Contract reports (transcript only — not written to any file):**

```
Field coverage check:
- entities[].fields: 124 required, 124 present, 0 missing
- endpoints[].request_body: 67 required, 67 present, 0 missing
- endpoints[].query_params: 0 required, 0 present, 0 missing
- endpoints[].path_params: 0 required, 0 present, 0 missing
Status: PASS
```
Two independent passes were run. Pass 1 diffed the structured identifier set against every backticked token in the PRD (fenced blocks stripped so backtick pairing was not skewed by the §2.2 JSON fences). Pass 2 re-scanned every snake_case token appearing anywhere in any scaffold *string* value, catching nested object keys described only in prose: the 56 residual hits were all formula-local variables (`raw_tol_mm`, `capped_tol_mm`, `weighted_offset_centi`, `tier_bp`, `rate_delta_bp`, `running_baseline_bp`, …), calculation names, complexity-profile labels, validation category labels, or enum-variant names — none are persisted fields or request identifiers. The two that needed manual confirmation were `body_chest` (a scaffold prose shorthand; the real keys `body_chest_min_mm`/`body_chest_max_mm` are backticked) and `size_labels` (plural prose for `size_label`; `unmapped_size_labels` is backticked).

```
Rule coverage check:
- validations[] with priority: 31 checked, 31 expressed in prose, 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (write_endpoint + expected_<parent>_version + error_id all named), 0 missing
- state_machines[].transitions: 44 checked (8 machines), 44 fully expressed, 0 missing
- calculations[]: 11 checked, 11 fully expressed, 0 missing
- validations[] conditions: 31 checked, 31 matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: 29 endpoints / 87 side-effect items checked, 87 expressed, 0 missing
- entities[].fields[] structured content: 124 checked, 124 reconstructible from prose, 0 missing
- sibling-branch symmetry: 14 groups checked, 14 with equal prose density, 0 asymmetric
Status: PASS
```
§2.9 carries the full 31-rank ladder with each rule's `applies_to` scope enumerated (including rank 9's ten operations and rank 10's fourteen action endpoints) plus three worked precedence consequences. Both dual-variant calculations (`fit_recommendation` → `history_weighted`/`population_fallback`; `intervention_savings` → `deployment_attributed`/`cohort_chronological`) are rendered with a shared skeleton plus per-variant divergence and the directional relationship between them. All 46 error ids and all 46 HTTP statuses were machine-verified against the scaffold; all 52 endpoint method+path pairs and all 52 authorized-role sets match the scaffold exactly (0 mismatches). §2.2 was diffed against `section-2.2-response-structure.md` and is byte-identical.

```
Path purity check (§3 only):
- backtick tokens scanned: 1050
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```
The only URL mount in the document is the system-wide `/fit-program` note in §2's lead-in, which the contract permits. §3.9's ops-run and clock capabilities use capability-description framing rather than paths.

One repair made during verification: a "roughly half a year" gloss on the 180-day abuse window (a forbidden fuzzy word) was rewritten to state the mechanism instead. A full re-scan for fuzzy/hedging language now returns nothing.

## Step 5: Generate unit tests — 2026-09-03T05:07:13.731Z

Launched in the SAME assistant message as Step 6 so the two ran concurrently — this is what gives the implementation generator physical isolation from `test_suite/` (the directory did not exist when impl-gen started). Orchestrator verification: `test_helpers/` has 9 modules, `test_suite/` has conftest.py + 17 test modules, 140 `def test_` functions total. Step 5 finished after Step 6 (05:07 vs 04:07 UTC) — ~93 min wall time under 32-way host contention.

Subagent summary (verbatim):

Suite is complete. Final state of the generated test infrastructure for task_2493:

**What I just added**
- `/home/ubuntu/github/CodingPRD/tasks/task_2493_fit_guidance_return_reduction_program/test_suite/test_17_version_pinning_clock_drift_and_immediate_reads.py` — 6 tests covering the last four non-stub corner instances:
  - `Corner/cross_cutting_complexity_layers/mapping_creation_with_a_stale_expected_item_version_returns_412` (2 tests: the pinned version 2 goes stale when a product-page write bumps the item to 3 → 412 `ERR_STALE_ITEM_VERSION`, readiness stays `UNVERIFIED`, zero mapping rows; then the identical body with version 3 → `ACTIVE` mapping, coverage 10000, item `CHART_MAPPED` at version 4)
  - `.../override_creation_with_a_stale_expected_customer_profile_version_returns_412` (1 test: profile v1 → TOPS 45-day override, reusing v1 for a BOTTOMS override → 412 `ERR_STALE_CUSTOMER_PROFILE_VERSION`, retry with v2 succeeds, two `CUSTOMER_OVERRIDE` rows and version 3)
  - `.../ops_run_ages_an_abuse_strike_out_of_the_trailing_window` (1 test: fee 0 / refund 2295 / total cost 1330; 1 strike + `WATCH` at 2026-01-10, clock to 2026-07-10, checkpoint reports `abuse_downgrades` 1 / `items_swept` 1 / no flips, profile back to 0 strikes + `CLEAR` with `refunded_total_cents` 2295 intact)
  - `Corner/consistency_model/immediate_consistency_exposes_the_fit_signal_pool_in_the_same_request_cycle` (2 tests: purchaser weight 200 / offset −50 visible on the next read, non-purchaser 100 / 0 taking the pool to 300 with both rows `ACTIVE`)

**Coverage, verified mechanically**
- 140 tests across `test_01` … `test_17`, all compiling.
- Queue B: all **54** non-stub corner instances translated (`untranslated real instances: []`); none of the **24** `excluded_because:` stubs was translated (`stub tags used: []`).
- Queue A: all **18** difficulty instances present with ≥3 tests each (minimum observed 3, max 5).
- Every test docstring: non-empty, carries a `PRD §` label and a quoted span, ends with exactly one `Design:` line, and every `Design:` tail resolves to a real `- name:` in the two design yamls (`missing 0`).

**Both mandatory final audits pass**
- PRD-citation pass: `non-verbatim quotes: 0` against a whitespace-normalized `workspace/PRD.md` (checks every quoted span ≥40 chars or containing a backtick); all **46** asserted `ApiErrorId` values appear in PRD prose before the §5 table, not only in it; the two precedence tests cite explicit PRD rank-ordering prose (§2.9 ranks 9/17/31); no `skip`/`skipif`/`xfail` markers anywhere in `test_suite/`.
- Scaffold-citation pass: C4 satisfied for all 140 tests (exactly one `Design:` line, verbatim from yaml `name:`); no test or helper mentions the design documents, and no unused imports in any test module.

The scope constraint was honored throughout: nothing under `workspace/implementation/` was read, listed, or created. The suite was not executed, since that requires the concurrently generated implementation.

## Step 6: Generate implementation — 2026-09-03T05:07:13.731Z

Orchestrator verification: `workspace/implementation/` contains `start.sh`, `requirements.txt`, `app.py`, 9 foundation modules, plus `routes/` and `services/` packages. One stray `python3 app.py` process with cwd inside the task tree was observed at 05:07 and had exited on its own before Step 7 launched, so no port contention was carried into the sweep.

Subagent summary (verbatim):

The implementation is complete and verified.

## What was built

`/home/ubuntu/github/CodingPRD/tasks/task_2493_fit_guidance_return_reduction_program/workspace/implementation/` — Python 3 + Flask, ~3,000 lines across 33 files, in-memory dicts only, zero seed data, boots clean from a fresh process via `bash start.sh` (guarded `pip install`, `exec python3 app.py`, `0.0.0.0:$PORT` default 10000).

Layout: `app.py` (blueprint registration, `ApiError`/`HTTPException` envelope handlers, `json.sort_keys = False`), foundation modules (`constants.py`, `errors.py`, `clock.py`, `numeric.py`, `db.py`, `response.py`, `middleware.py`, `validate.py`, `lookup.py`), 13 route blueprints, and 6 service modules (`derive`, `spec_verify`, `policy`, `returns`, `recommend`, `deployments`).

All **52** declared endpoints are registered with exactly the scaffold's role lists (verified by diffing extracted `authenticate(...)` calls against the scaffold endpoint table). `pyflakes` is clean.

## Verification

Three throwaway HTTP smoke suites (in `/tmp`, not in the task tree) all pass against fresh `bash start.sh` boots. Confirmed behaviors include:

- Tolerance resolution `pct → abs max → ceiling cap → stretch floor` (RIGID CHEST = 15 mm, STRETCH = 22 mm, floored per PRD §108/§207); violation → `CORRECTION_REQUESTED` + 2,500-cent vendor debit → resubmit → `VERIFIED`; budget exhaustion → `ERR_VENDOR_CORRECTION_BUDGET_EXHAUSTED` (402) with vendor `PROBATION`.
- Publish-guidance ladder to `GUIDANCE_READY`; OCC retry on mapping create → 412; both readiness cascades (chart retire → mapping `SUPERSEDED`/`CHART_RETIRED` → readiness `UNVERIFIED` → badge deployment `TERMINATED`/`MAPPING_SUPERSEDED` with `window_end` rewritten to the clock; delist → `ITEM_DELISTED`).
- Cost postings exact: FIT refunded = 1,881¢ (795+558+180+0+348); QUALITY/SALVAGE = 5,183¢ including `VENDOR_CHARGEBACK_CREDIT` −4,800 on gross; denied = 2 rows only; void writes one negating `REVERSAL` per `ORIGINAL` (sum 0), `total_cost_cents → 0`, fee/refund preserved, line back to `DELIVERED`, and walks an item out of `CHRONIC`.
- Restocking tiers with the 15000-bp `RESTRICTED` multiplier (1,200 → 1,800¢), abuse ladder by strikes and by rate, `RESOLVED_DENIED` when the purchaser is `BLOCKED`, and ops-run strike aging (`abuse_downgrades: 1`).
- Both recommendation variants diverge as specified on identical data: `population_fallback` (sample 8, confidence 6000) vs `history_weighted` (sample 3, confidence 7500).
- Ops-run one-hop rule: `ACTIVE → MEASURED` genuinely takes two runs.

## Notes for the caller

- Two `python3 app.py` processes with cwd `task_2493.../` (no `PORT`) and eleven under `task_2494.../implementation` are running but are not mine — I left them alone.
- `test_suite/`, `test_helpers/`, and both `SCAFFOLD_*_DESIGN.yaml` files were never read or written.

## Step 7: Run tests and iterate — 2026-09-03T05:29:02.885Z

Orchestrator independently re-verified the final sweep rather than trusting the subagent's claim: all 8 of `workspace/implementation/results.{1..8}.json` exist (written 05:19), and each parses to `passed 140 / total 140 / failed 0 / errors 0 / skipped 0`. `workspace/sweep.log` contains zero occurrences of `Terminated`, confirming the setsid wrapper held and no round was reaped mid-request. A grep of `test_suite/` for `skip`/`xfail` returns only three prose/identifier matches inside docstrings and a test name (`test_a_draft_chart_cannot_skip_standardization_...`) — no pytest markers. Per-round duration ~261s for 140 tests under per-test-server isolation.

Step 8 will run: Step 7 applied 3 `test_suite/` fixes, so the skip condition (0 deletions AND 0 test_suite fixes AND 0 test_helpers fixes AND 0 implementation fixes) is not met.

Subagent summary (verbatim):

All 8 parallel rounds are green: 140/140 in every round, 0 failures, 0 errors, 0 skipped, no `Terminated` reaping artifacts.

## Summary

**Iterations run:** 2 (2 × 8-round parallel sweeps, 140 tests each).

**Iteration 1 result:** 137/140 in all 8 rounds — the same 3 tests failed in every round (deterministic, not flakiness, not load-induced).

**Tests deleted:** none. All three failures were STEP 2 test bugs (assertion mis-translations of PRD), not PRD-silence cases.

**Fixes applied to `test_helpers/`:** none — no fixture, factory, or role-header helper was at fault. The three failures shared no upstream setup call.

**Fixes applied to `test_suite/`:**

1. `/home/ubuntu/github/CodingPRD/tasks/task_2493_fit_guidance_return_reduction_program/test_suite/test_08_window_adjacency.py`, `test_a_window_starting_where_the_previous_one_ends_is_admitted` — asserted `august["window_start"] == "2026-08-01T00:00:00Z"` / `window_end == "2026-09-01T00:00:00Z"`, i.e. byte-verbatim echo of the client-supplied instant. PRD §2.4 fixes the three-fractional-digit rendering (`2026-08-01T00:00:00.000Z`) only for `created_at`/`updated_at`; it says nothing about how client-supplied instants such as `window_start`/`window_end` are rendered back. A PRD-faithful reader may echo the input string or normalize to the house format — non-unique, so under STEP 1c the covered part (the instant's value, which is what the half-open adjacency rule is about) was kept and the uncovered part (fractional-digit rendering) dropped, via `.startswith("2026-08-01T00:00:00")`. This is the idiom the other 13 instant assertions in this suite already use (`test_03:184`, `test_04:359`, `test_11:166`, `test_12:454`, `test_15:115/166`, `test_17:253`, …) — these two sites were the outliers.
2. Same file, `test_an_override_starting_on_the_day_another_ends_collides` — identical issue on `built["override"]["effective_to"]`; same correction. The `ERR_POLICY_WINDOW_OVERLAP` / 409 assertion that the test actually exists to make was already correct and untouched.
3. `/home/ubuntu/github/CodingPRD/tasks/task_2493_fit_guidance_return_reduction_program/test_suite/test_12_derived_arithmetic_corners.py`, `test_the_second_strike_takes_the_shopper_from_watch_to_restricted` — asserted `return_rate_bp == 10000`; corrected to `6666`. Straight arithmetic error in the test. PRD §3.8: "`return_rate_bp` is `return_case_count` multiplied by 10,000, divided by `purchase_line_count`, with any fraction discarded." The fixture builds 3 delivered lines and resolves 2 change-of-mind cases, and the test itself asserts `purchase_line_count == 3`, so `floor(2 × 10000 / 3) = 6666`. The docstring's trailing gloss ("even at a return rate of 10,000 basis points") carried the same error and was rewritten; the verbatim PRD quote in the docstring was left intact. The test's actual point — that the rate arm of the BLOCKED rule stays out of reach because it additionally requires `purchase_line_count >= 4` — holds unchanged.

**Fixes applied to `implementation/`:** none. `services/derive.py::apply_customer_derivation` already computed `return_case_count`, `purchase_line_count`, and `return_rate_bp` exactly as §3.8 states, and the timestamp normalization is consistent with §2.4 — so no PRD-required behavior was weakened to accommodate a test.

## Step 8: Finalize PRD — 2026-09-03T05:39:54.648Z

Orchestrator verification: `diff PRD.md PRD_FINALIZED.md` is a single hunk `90a91,92` — one inserted paragraph in §2.4, zero deletions, zero revisions to existing prose. 448 → 450 lines. The insertion is in scope (it pins the instant-rendering silence that drove Step 7 test_suite fixes 1 and 2); no §3.8 edit was made, correctly, since item 3 was a test arithmetic bug on a rule PRD already determines. File still ends at the §5 error-table boundary.

Subagent summary (verbatim):

`PRD_FINALIZED.md` is written. Only one of the three Step 7 items was a genuine PRD silence; the third was a pure test arithmetic bug that PRD §3.8 already determines uniquely.

## Line counts
- `PRD.md`: 448 lines
- `PRD_FINALIZED.md`: 450 lines
- Delta: +2 lines (+0.45%); one inserted paragraph, zero deletions, zero revisions to existing prose.

## Changes
- **§2.4 (Common Resource Properties) — insert — instant rendering for every non-`created_at`/`updated_at` instant field, including client-supplied ones: parsed, normalized to UTC, and re-rendered in the three-fractional-digit house format rather than echoed byte-for-byte (`2026-08-01T00:00:00Z` in → `2026-08-01T00:00:00.000Z` out) — `implementation/response.py:43` (`serialize` → `clock.iso` for every `datetime`), `implementation/clock.py:31-36` (the format itself), `implementation/routes/clock_control.py:20` (`current_utc`).**

Nothing was changed for Step 7 items 1/2's 409/`ERR_POLICY_WINDOW_OVERLAP` and half-open-adjacency assertions (PRD §2.9 rank 23/24 and §3.9 already pin those), and nothing was changed for item 3 — `services/derive.py:284-297` computes `purchase_line_count`, `return_case_count`, and `return_rate_bp` exactly as §3.8 states, and `derive.py:312-315` implements the `purchase_line_count >= 4` arm of the BLOCKED rate rule verbatim, so §3.8 stays untouched.

## Pre-edit search log

**Edit 1 — §2.4 instant rendering**

(a) Subject identified: how the API renders any instant-valued field in a response body, in particular instants that originated as client input (`window_start`, `window_end`, `effective_to`) rather than from the clock.

(b) Impl paths enumerated (read or grepped):
- `implementation/response.py:26-45` — `serialize()` is the single sink for every response body; it walks dicts/lists recursively and routes *every* `datetime` through `clock.iso`. Both `object_response` and `array_response` call it, so no route can bypass it.
- `implementation/clock.py:31-36` — `iso()` = `%Y-%m-%dT%H:%M:%S.` + `%03d` of `microsecond // 1000` + `Z`, after `astimezone(timezone.utc)`. Returns `None` for `None`.
- `implementation/routes/clock_control.py:20` — the one place a response builds an instant string outside `serialize`; it also calls `clock.iso`, so `current_utc` carries the same format. Confirmed no test pins `current_utc` verbatim (`grep current_utc test_suite/ test_helpers/` → only the client helper).
- `implementation/validate.py:132-157` — `parse_instant`/`req_instant`/`opt_instant`: strips `Z`/`z`, `fromisoformat`, assumes UTC when naive, then `astimezone(utc)`. So every stored instant is a UTC-normalized `datetime`, never the client's original string.
- All client-supplied-instant intake sites: `routes/order_lines.py:27,40` (`delivered_at`), `routes/policies.py:22-23,35-36` (`effective_from`/`effective_to`, shared by `routes/customers.py:61-91` override create), `routes/interventions.py:80-81,112-113` (`window_start`/`window_end`), `routes/clock_control.py:18` (`to_iso8601`). None stores a raw string.
- Server-minted instant sites: `db.py`/`new_row` + `touch` (`created_at`/`updated_at`), `routes/specs.py:154` (`verified_at = clock.now()`), `routes/cases.py:89-90` (`return_deadline_at`, `requested_at`), `services/policy.py:44-45` (deadline arithmetic), `services/derive.py:240-241` and the terminate/delist/retire paths (`window_end` rewritten to the clock — a `datetime`, so it renders the same way).
- Off-Step-7 mutation of the same fields confirmed consistent: `window_end` is overwritten with `clock.now()` in delisting, chart-retirement supersession, chronic cascade, ops-run `WINDOW_ELAPSED`, and manual terminate — all `datetime`, all rendered by the same sink.
- Negative check: `grep` for `isoformat|strftime|000Z` across `implementation/` found no second formatter; `constants.py:265 CLOCK_EPOCH_ISO` is a dead string never emitted.

(c) Wording adjustments made to keep all enumerated paths consistent:
- Phrased the claim as universal over "every other instant-valued field the API returns" with the field names as illustrative examples, since the single `serialize` sink makes the universal form true and a closed list would risk being read as exhaustive/exclusive.
- Explicitly included `current_utc` and cited §2.5, because that field is produced outside `serialize` yet uses the same formatter — omitting it would have left a reader free to format it differently.
- Dropped a draft clause asserting the instant's *value* is unchanged by normalization. `clock.iso` truncates sub-millisecond precision (`microsecond // 1000`), so "value unchanged" would have been a false universal for microsecond-precision input; the sentence now speaks only about rendering and UTC normalization.
- Said "normalized to UTC" rather than enumerating accepted input syntaxes, to avoid narrowing `validate.parse_instant`'s tolerance (offset-bearing, naive, and `z`-suffixed forms) — a surface Step 7 never exercised.

## Step 9: Complete PRD — 2026-09-03T06:02:33.818Z

ORCHESTRATOR DECISION (recorded per the autonomy instruction): the 3495-line implementation is too large for one subagent to scan exhaustively in a single pass, and the known failure mode of this step is a subagent producing a `PRD_COMPLETED.md` byte-identical to its source — i.e. the scan silently never ran. I therefore split Step 9 into three SEQUENTIAL passes over disjoint, explicitly enumerated file partitions of `implementation/`, each pass editing the same `PRD_COMPLETED.md` in place and additively:

- Pass A — foundation/cross-cutting (~1100 lines): app.py, middleware.py, errors.py, response.py, clock.py, numeric.py, db.py, lookup.py, validate.py, constants.py, routes/__init__.py, routes/clock_control.py. Created PRD_COMPLETED.md via `cp PRD_FINALIZED.md`. Result: 11 in-place revisions (10 ambiguity-pins, 1 mismatch).
- Pass B — supply side (~1030 lines): routes/vendors.py, items.py, specs.py, charts.py, mappings.py, feedback.py, services/spec_verify.py, services/recommend.py. Forbidden from re-cp'ing. Result: +14 edits (13 ambiguity-pins, 1 mismatch), cumulative 25 changed lines.
- Pass C — demand side (~1360 lines): routes/customers.py, policies.py, order_lines.py, cases.py, interventions.py, ops_runs.py, services/policy.py, returns.py, deployments.py, derive.py. Result: +24 edits (20 ambiguity-pins, 4 mismatches), cumulative 49 changed lines.

Each later pass verified the earlier passes' edits survived: pass B grepped one distinctive phrase from each of pass A's 11 revisions (1 hit each) and confirmed the changed-line set was unchanged; pass C snapshotted the file before starting and showed its own 24 changed lines had ZERO overlap with the pre-existing 25, so no prior edit was clobbered.

Orchestrator's own final verification: `diff PRD_FINALIZED.md PRD_COMPLETED.md` reports 98 `^[<>]` lines = 49 lines revised in place; `cmp` confirms the file is NOT byte-identical to its source (the no-op failure mode did not occur); char counts 97,701 (PRD.md) → 98,385 (PRD_FINALIZED.md) → 113,110 (PRD_COMPLETED.md), i.e. +14,725 chars of pinning prose over the Step 8 output; line count held at 450 (every edit in-paragraph, no new sections); heading count 28, identical to PRD.md; and the file ends on the last row of the §5 error table — a real section boundary, not mid-sentence. `implementation/` was not modified by Steps 8 or 9, so the Step 7 green sweep (8/8 rounds, 140/140) remains the valid test result.

Aggregate across the three passes: 43 ambiguity-pins, 6 mismatch-revisions, 49 total edits, 0 new sections, 0 §4/§5 table row changes.

### Pass A summary (verbatim)

All 11 edits landed as in-place line revisions. PASS A complete.

## PASS A summary

**Setup**: `cp PRD_FINALIZED.md PRD_COMPLETED.md` done as first action; only `PRD_COMPLETED.md` was edited (`PRD.md` and `PRD_FINALIZED.md` untouched).

**Verification**: `diff PRD_FINALIZED.md PRD_COMPLETED.md | grep -c '^[<>]'` → **22** (11 `<` / 11 `>`, i.e. 11 lines revised in place, no lines added or removed). Line counts: both files 450 lines. No sections, table rows, or bullets added.

**Counts**: ambiguity-pins **10**, mismatch-revisions **1**.

### Changes
- §2.1 — revise — ambiguity — an empty `X-User-ID`/`X-User-Role` header value counts as absent, and the role-name comparison is exact/case-sensitive — `middleware.py:19-26`
- §2.2 success bullet — revise — ambiguity — `api_request_id` is `req_` + exactly 20 chars from A–Z0–9 — `response.py:11-15`
- §2.2 success bullet — revise — ambiguity — the four pagination `meta` fields appear only on the paginated collection reads; the case cost-postings read is an unpaginated `array` response that ignores `limit`/`offset` — `response.py:56-65`, `routes/cases.py:248-252`
- §2.2 error bullet — insert — ambiguity — undefined path → `ERR_NOT_FOUND` (404) and undefined method → `ERR_METHOD_NOT_ALLOWED` (405), in the same envelope, explicitly outside the §5 catalogue (no §5 rows touched) — `app.py:29-40`
- §2.3 ¶1 — insert — ambiguity — integer-literal grammar for `limit`/`offset` (digits, optional leading sign, whitespace stripped; empty/fractional/other text rejected), absent params take defaults and are never range-checked, `offset` unbounded above and yields an empty page past `total_count` — `validate.py:269-303`, `validate.py:306-315`
- §2.3 ¶2 — insert — ambiguity — `created_at` ties broken by server creation order (matters under a frozen clock); `has_more` = `offset` + rows returned < `total_count` — `db.py:86-88`, `validate.py:313`
- §2.3 ¶3 — insert — ambiguity — filters are exact case-sensitive string equality, no-match yields empty array not an error, undeclared query params ignored — `lookup.py:75-90`
- §2.4 ¶2 — insert — ambiguity — supplied instants accept `Z` or an explicit offset (converted to UTC); a zone-less instant is read as UTC — `validate.py:132-144`
- §2.4 ¶3 — **revise — mismatch** — PRD said "a recomputation of a derived field counts as a mutation" flatly; impl bumps `updated_at`/`version` only when a value actually changes, so a no-op recompute (e.g. an ops-run sweep finding everything already correct) bumps nothing — `db.py:72-83` (used by `services/derive.py:100,109,164,198,237,273,340`, `routes/ops_runs.py:47,59`)
- §2.5 — revise — ambiguity — `to_iso8601` is required and parsed per §2.4 (absent/unparseable → `ERR_INVALID_REQUEST`); response `data` has `current_utc` as its only field, in house format — `routes/clock_control.py:14-20`
- §2.9 rank 5 — insert — ambiguity — explicit-`null` key treated as absent (required → reject, optional → default); undeclared body keys ignored; integer fields must be JSON integers (bool/numeric-string/fractional rejected); strings stored untrimmed with case-sensitive enum membership; absent/blank body read as `{}`, non-JSON or non-object body is itself `ERR_INVALID_REQUEST` — `validate.py:15-25,41-49,52-126`

### Deliberately left unpinned
- **Error `message` wording** (e.g. `"'x' is required."`, `"Vendor 'id' not found."`): PRD already declares `message` merely human-readable; pinning strings would over-constrain and no error identity depends on it.
- **Intra-request order of multiple rank-5 field failures**: all such failures share `ERR_INVALID_REQUEST`/400, so field ordering only changes the message, not observable behavior.
- **Envelope key order** (`meta`, `response_type`, `data`; and `limit,offset,total_count,has_more` inside `meta`): already fixed by the §2.2 JSON samples, which match `response.py` exactly (`app.json.sort_keys = False`).
- **`_seq` and other underscore-prefixed internal keys**: stripped by `serialize`, never on any surface.
- **`numeric.py` primitives** (`round_half_up` half-away-from-zero, `floor_div`, `bp_rate`, `clamp`, division-by-zero → 0): §2.6 plus each call-site paragraph already state the mode and the zero-denominator result; nothing was left open.
- **`constants.py`**: every threshold/tier/weight/enum in the file already appears verbatim in PRD prose (tolerance ceilings, stretch multipliers, 3-round cap, 2,500-cent debit, 8,000 bp coverage, 3 detail images, restock tiers, 15,000 bp abuse multiplier, freight/labor/handling/refurb/markdown/payment/chargeback figures, 7,500/2,500 weights, 1,500/2,500 thresholds, 180-day window and strike ladder, 7,000 bp / 4-line rate rule, policy deltas and 7-day floor, per-category saved-cost table, 5,000-cent funding tolerance, vendor penalties and bands, pagination, clock epoch). `ABUSE_STATUS_RANK` and `MEASUREMENT_POINT_ORDER` are internal-only and expose nothing.
- **`_find`'s non-string id guard** (`lookup.py:10-11`): unreachable from Flask path params, which are always strings.
- **Whitespace-only conversion column counting as empty at standardize** (`routes/charts.py:97`): belongs to the chart-route slice owned by pass B/C.

### Pass B summary (verbatim)

All 14 edits applied. Verification complete.

## Summary — Pass B (supply side)

**Pass A preserved.** I did NOT `cp` anything over `PRD_COMPLETED.md`; every change was an in-place `Edit` on an exact unique substring. Verified pass A's 11 revisions survive two ways: (a) `diff PRD_FINALIZED.md PRD_COMPLETED.md` still reports changes at exactly lines 17, 46, 50, 72, 76, 78, 80, 91, 93, 99, 138 — pass A's 11 lines, untouched; (b) grepped one distinctive phrase from each of the 11 (`exact and case-sensitive`, `exactly 20 characters`, `accepts no limit or offset at all`, `ERR_METHOD_NOT_ALLOWED`, `base-10 digit string`, `the order in which the rows were created on the server`, `exact, case-sensitive string equality`, `no zone designator at all`, `bumps no versions at all`, `single field is current_utc`, `Four conventions make this rank deterministic`) — each returns exactly 1 hit.

**Diff counts.** Before: `22` (11 changed lines). After: `50` (25 changed lines). Line counts unchanged at 450 / 450 — every edit was an in-paragraph insert or revision; no new paragraphs, no new sections, no table-row changes.

**Counts.** 13 ambiguity-pins, 1 mismatch-revision (14 edits total).

### Changes
- §2.6 — revise — mismatch — the half-away-from-zero convention was scoped only to the size-step conversion; impl uses one `round_half_up` (Decimal `ROUND_HALF_UP`, away from zero) for the grade-tolerance percentage component and the weighted fit offset too. Widened to all three. — `numeric.py:12`, `spec_verify.py:14`, `recommend.py:174`
- §3.1 — insert — ambiguity — item create defaults `model_measurements_published` false and `detail_image_count` 0 (PRD listed only the derived-metric zeros, `pdp_review_required`, `delist_reason_code`, `model_height_cm`, `model_worn_size_label`). — `items.py:86,89`
- §3.1 — insert — ambiguity — a second delist of an already-`DELISTED` item is `ERR_INVALID_ITEM_STATE`, not `ERR_ITEM_DELISTED`, since delist is absent from the rank-9 list. — `items.py:171`
- §3.2 — insert — ambiguity — none of `chest/waist/hip/inseam_mm`, `increment_mm`, `tolerance_pct_bp`, `tolerance_abs_mm` carries a bound (zero/negative accepted); only `sort_index` is floored at 0. — `validate.py:172-179,204-206`
- §3.2 — insert — ambiguity — `tolerance_applied_mm` opens as an empty array on a new spec. — `specs.py:84`
- §3.2 — insert — ambiguity — the `REJECTED` readiness drop bumps `version` by 1 but terminates no deployment and leaves `listing_status` and the active mapping alone (unlike the retire/chronic cascades). — `specs.py:177`, `derive.py:223`
- §3.2 — insert — ambiguity — resubmit does not clear `violation_count`, `first_violation_point`, `first_violation_from_size_label`, `tolerance_applied_mm`; they keep the prior run's values. — `specs.py:208-213`
- §3.3 — insert — ambiguity — chart `retire_reason_code` opens null, and draft-time validation checks neither band ordering/overlap nor conversion-column emptiness, so such a chart is a legal `DRAFT` and fails only at standardize. — `charts.py:102`, `validate.py:229-232`
- §3.3 — insert — ambiguity — the retirement cascade drops readiness only when there is something to drop; an item already `UNVERIFIED` keeps its `version` and none of its deployments are terminated. — `charts.py:184-185`, `derive.py:223-229`
- §3.3 — revise+insert — ambiguity — mapping create never terminates a deployment even when it pulls the item back from `GUIDANCE_READY`; and the "two circumstances" of a fall to `UNVERIFIED` are actually three (chart retirement, spec reopened into `CORRECTION_REQUESTED`, verification landing on `REJECTED`), from `CHART_MAPPED` **or** `GUIDANCE_READY`. — `mappings.py:281`, `specs.py:177`
- §3.4 — revise — ambiguity — pdp-enhancement bounds (`detail_image_count` ≥ 0, `model_height_cm` ≥ 0, `model_worn_size_label` ≥ 1 char) plus the key semantics: the two optional fields are a *partial* update — omitted or explicitly `null` leaves the stored value as it was rather than nulling it — and `version` bumps by 1 even when nothing changed. — `items.py:193-210`
- §3.5 — insert — ambiguity — `purchased_size_label` is any non-empty string, never validated against spec/mapping/chart/order lines; `comment` is stored verbatim with no length bound and is null when omitted. — `feedback.py:31,33,56`
- §3.6 — insert — ambiguity — `customer_profile_id` is an optional **query** parameter and is the value the §2.1 ownership check compares; a `Customer` omitting it passes and gets the population variant; the parameter is not a foreign key (unknown id is not a 404, empty value counts as absent); a missing `ACTIVE` mapping or missing chart is also `ERR_GUIDANCE_NOT_READY`. — `items.py:262-276`
- §3.6 — revise — ambiguity — the personal anchor's order-line sort has a third tie-break after `delivered_at` desc and `created_at` desc: reverse ingest order. — `recommend.py:187-188`

### Deliberately left unpinned
- **Ownership scoping absent on `GET /measurement-specs`, `GET /fit-feedback`, `GET /fit-feedback/{id}`** (a `VendorUser` sees other brands' specs; a `Customer` sees others' feedback). §2.1 already enumerates the ownership checks exhaustively and these reads are not among them — derivable, no edit needed.
- **Feedback creation is allowed on a `DELISTED` item.** Rank 9 of §2.9 enumerates exactly ten operations and fit-feedback creation is not one — already pinned by omission.
- **Validation-order details inside my slice** (e.g. `brand_code` length before charset; the stored-`size_points` recheck on submit preceding the `DRAFT` check; body-FK order item→chart on mapping create, item→customer on feedback create; the rank-4 body peek preceding rank 5 on spec and feedback create) — all fall out of the §2.9 ladder as written plus its "declaration order" clause.
- **`recompute_item` on feedback publish/retract bumping the item's `version`** — follows from pass A's §2.4 revision ("a recomputation counts as a mutation when it changes a stored value") together with §3.5's already-pinned pool deltas.
- **Internal-only helpers** — `_median_row_index`, `TOLERANCE_CEILING_MM`/`STRETCH_MULTIPLIER_PCT` lookup shape, `ordered()`'s `_seq` key (surfaced only where it decides a visible ordering, which I did pin in §3.6) — no response or error exposes them.
- **§4 endpoint table and §5 error catalogue** — I audited every route in my slice against both: all authorized-role sets match impl exactly and every error id impl raises is present with the right status. No row contradicted impl, so I changed nothing there.

### Pass C summary (verbatim)

Pass C complete.

## Integrity confirmation

- I did **not** `cp` anything over `PRD_COMPLETED.md`; every change was an in-place `Edit`.
- Before starting I snapshotted `PRD_COMPLETED.md` to `/tmp/PRD_COMPLETED_pre_c.md` and recorded the pre-existing changed-line numbers (17, 46, 50, 72, 76, 78, 80, 91, 93, 99, 109, 138, 188, 192, 196, 198, 221, 223, 229, 233, 239, 243, 251, 259, 265 — 25 lines). `diff /tmp/PRD_COMPLETED_pre_c.md PRD_COMPLETED.md` now reports changes on exactly my 24 lines (137, 148, 166, 273, 275, 277, 279, 281, 283, 287, 291, 293, 306, 310, 312, 322, 324, 326, 328, 330, 332, 334, 336, 340) — **zero overlap** with the prior-pass set, so all 25 earlier revisions are byte-identical and intact.
- File still ends at a real section boundary: last line is `` | `ERR_VENDOR_CORRECTION_BUDGET_EXHAUSTED` | 402 Payment Required | ``. §4 endpoint table and §5 error table row sets untouched (all my edits are at line ≤ 340).

## Numbers

- `diff PRD_FINALIZED.md PRD_COMPLETED.md | grep -c '^[<>]'`: **50 → 98** (25 + 24 = 49 revised lines, all in place).
- Line counts: PRD_FINALIZED 450, PRD_COMPLETED 450 (unchanged — no new paragraphs, no new sections).
- Chars: PRD.md 97,701 · PRD_FINALIZED 98,385 · PRD_COMPLETED 113,110. Source-vs-completed delta: **+15,409** chars vs PRD.md, **+14,725** vs PRD_FINALIZED (my pass contributed +7,603).
- Counts this pass: **20 ambiguity-pins, 4 mismatch-revisions** (24 edited lines total).

## Changes

- §2.9 rank 4 — revise — mismatch — "Applies to every `VendorUser` and `Customer` operation" was false; now enumerates the ownership-checked operations (spec create/submit/resubmit + vendor read; return-case create + single read, feedback create/retract, fit-recommendation read) and states that a customer profile, an order line or its list, a feedback row or its list, a spec or its list, and a catalog item are served unchecked — customers.py:48, order_lines.py:55/61, feedback.py:72/78, specs.py read/list
- §2.9 rank 15 — insert — ambiguity — a missing policy always reports `ERR_NO_RETURN_POLICY`, never `ERR_RETURN_WINDOW_CLOSED`, because the deadline can't be computed without resolution — cases.py:58-63
- §2.9 closing paragraph — insert — ambiguity — rank 4 peeks `order_line_id` out of the unvalidated body, so a non-owner with a malformed body gets `ERR_NOT_RESOURCE_OWNER`; a value that is absent/non-string/unresolvable skips the peek and lets ranks 5/7 decide (spec create peeks `item_id` the same way) — cases.py:34-39, specs.py:44-47
- §3.7 ¶1 — insert — ambiguity — `email` min length 1, uniqueness by exact case-sensitive equality — customers.py:22-28
- §3.7 ¶2 — insert — ambiguity — no ordering check binds `effective_to` to `effective_from`; an inverted interval is accepted and simply never resolves — policies.py:22-23, policy.py:16-18
- §3.7 ¶3 — insert — ambiguity — the overlap scan looks only at `CUSTOMER_OVERRIDE` rows of the same shopper+category; category defaults are not interval-checked at all and may overlap freely — customers.py:75-86, policies.py:40-47
- §3.7 ¶4 (order lines) — insert — ambiguity — `size_label` need only be non-empty and is never checked against spec/mapping/chart — order_lines.py:23
- §3.7 ¶4 — insert — ambiguity — `delivered_at` is unbounded against the clock; a future instant is accepted — order_lines.py:27
- §3.7 ¶4 — insert — ambiguity — an ingest can by itself lift a shopper out of rate-driven `BLOCKED` by diluting `return_rate_bp` — order_lines.py:48, derive.py:312-315
- §3.7 ¶5 (opening a return) — insert — ambiguity — `comment` is type-checked then discarded; no comment field on the case or in any response — cases.py:44
- §3.7 last ¶ — insert — ambiguity — `requested_reason_code` is its own stored field, echoed on reads and never rewritten by a reclassification — cases.py:82-84, 156-157
- §3.7 policy-ranking ¶ — insert — ambiguity — final tie-break after `created_at` is later server creation order — policy.py:27-34
- §3.8 classify ¶ — insert — mismatch — `evidence_note` is not stored (PRD implied it was recorded) — cases.py:149
- §3.8 resolve ¶ — insert — mismatch — `resolution_note` is likewise type-checked and discarded — cases.py:170
- §3.8 denied-outcomes ¶ — insert — ambiguity — a denied change-of-mind leaves `change_of_mind_count` untouched, and a denied quality case adds no `quality_chargeback_count` even though the vendor recomputation runs — derive.py:83, 290-292
- §3.8 chronic-cascade ¶ — insert — ambiguity — a chronic flip on a `CHART_MAPPED` item terminates **no** deployment (unlike chart retirement, which does terminate from `CHART_MAPPED`), and the flip lands three separate item mutations (`version` +3) when the item was `LISTED` + `GUIDANCE_READY` — derive.py:174-176/182-208, charts.py:128-129
- §3.8 reversal ¶ — insert — ambiguity — a void also leaves the readiness axis, a raised `pdp_review_required`, and cascade-terminated deployments alone — cases.py:238, derive.py:161-167
- §3.9 ¶1 — insert — ambiguity — intervention `name` is 1–200 characters — interventions.py:25
- §3.9 ¶2 — insert — ambiguity — `terminated_reason_code` also opens null on a new deployment — interventions.py:122
- §3.9 early-stop ¶ — revise — mismatch — the operator may send **any** of the four `terminated_reason_code` values and it is stored as supplied; `MANUAL_STOP` is not enforced — interventions.py:155-156
- §3.9 one-hop ¶ — insert — ambiguity — `TERMINATED → MEASURED` has no clock condition (so an early stop, delist or readiness fall is measured by the very next run) and the run's three passes are fixed: deployments, then catalog, then shoppers — ops_runs.py:37-76, derive.py:242
- §3.9 measurement ¶ — insert — ambiguity — a deployment terminated straight out of `SCHEDULED` is still measured, with the missing baseline rate read as 0 while `baseline_units_count`/`baseline_return_rate_bp` stay null — deployments.py:43-63
- §3.9 sweep ¶ — insert — ambiguity — full semantics of all eight ops-run counters (hop-only deployment counters, cascade terminations excluded, `items_swept` counts every item, flip counters count actual changes to `WATCH`/`CHRONIC` only, `corrections_opened`, `abuse_downgrades` = improvements only) and that the response is a bare counter object — ops_runs.py:25-77, derive.py:169-176/343-345
- §3.9 roll-up ¶ — insert — ambiguity — `deployment_count` counts deployments in any status, `measured_deployment_count` only `MEASURED` — derive.py:256-260
- §3.9 savings-report ¶ — insert — ambiguity — empty `variant` counts as omitted; an unrecognized value is `ERR_INVALID_REQUEST`, and only after the path intervention resolves — interventions.py:55-60
- §3.9 cohort variant ¶ — insert — ambiguity — cohort ordering carries a final creation-order tie-break, and the report's `avoided_return_count` is the recomputed cohort sum, not the sum of stored per-deployment counts — deployments.py:93-115

## Deliberately left unpinned

- **Intra-rank-5 field order** (e.g. policy fields read before `expected_customer_profile_version`): both paths yield `ERR_INVALID_REQUEST` 400, so order is observable only in the human-readable message.
- **No item recompute on case opening / no recompute on classify**: derived item values provably cannot change there, and `mutating()` bumps nothing when values are unchanged, so there is no observable difference.
- **`snapshot_baseline` not filtering line status**: all four order-line statuses are "purchased", so the missing filter can never change the result.
- **Full field-by-field recomputation inside `apply_item_derivation`/`apply_customer_derivation`** (e.g. feedback totals re-summed on an order-line ingest): idempotent, no surfaced difference.
- **Internal `_hop_run` / `_seq` bookkeeping keys**: stripped by the serializer, never in any response; their *effects* are pinned instead (one hop per run, creation-order tie-breaks).
- **Ledger read ordering**: already covered by §2.3's default `created_at`-ascending rule plus §2.2's no-pagination clause from pass A, so originals-then-reversals follows without new prose.
- **Exact `version`-bump totals for multi-row cascades other than the chronic flip**: derivable from §2.4/§2.8 and pinning each would mean a per-branch arithmetic table with no matching impl surface.

## Pipeline complete — 2026-09-03T06:02:33.818Z

All nine steps finished. Final deliverables in place: SCAFFOLD.yaml + both design indices, `test_helpers/` (9 modules), `test_suite/` (17 modules, 140 tests, 0 deleted), `workspace/implementation/` (Python+Flask, 3495 lines, in-memory only, 52 endpoints), `workspace/PRD.md` → `PRD_FINALIZED.md` → `PRD_COMPLETED.md`, and `results.{1..8}.json` all green at 140/140.
