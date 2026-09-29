# Worklog — task_2558_healthcare_group_purchasing_contract_compliance

## Step 1: Create task directory — 2026-09-03T10:03:48.000Z

Created pre-assigned directory `/home/ubuntu/github/CodingPRD/tasks/task_2558_healthcare_group_purchasing_contract_compliance` and its `workspace/` subdirectory. Index 2558 was fixed by the scenario number; no index allocation scan was performed (other pipelines run concurrently on this host).

## Step 2: Generate scaffold artifacts — 2026-09-03T12:06:00.000Z

Wrote the three scaffold artifacts from the scenario description and the scaffold-generator
specification alone (no sibling task under `tasks/` was inspected):

- `SCAFFOLD.yaml` (2876 lines) — §1.0–§1.7: 11 entities, 9 state machines over 8 entities,
  2 concurrency rules, 9 calculations (2 dual-variant), 24 validation priorities plus
  3 declared priority conflicts, 67 endpoints, 57 error codes, 6 roles under
  `role_model: segregation_of_duties`.
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (2345 lines) — §1.8, 22 instances.
- `SCAFFOLD_CORNER_DESIGN.yaml` (4237 lines) — §1.9, 85 instances across all nine
  claim-extraction sections (63 with `test_recipe`, 22 `excluded_because` stubs citing §1.8).

Two scaffold-level corrections were made while linting §1.9 against §1.5:
`Commitment.ytd_leakage_pct` was added as a computed field (the load cascade and the leakage
alert already keyed on it), and the five nested FK reverse-reachability reads were converted to
filtered top-level lists (`GET /gpo/contract-items`, `/gpo/clinical-evidence-reviews`,
`/gpo/compliance-measurements`, `/gpo/admin-fee-distributions`, `/gpo/purchase-lines`), which
matches the flat topology and keeps the endpoint count at 67.

`scaffold_lint.py` verdict: clean lint (1156 calls scanned across §1.8+§1.9).

## Step 2 (orchestrator record — verbatim subagent summary) — 2026-09-03T12:06:30.000Z

The three scaffold artifacts for task 2558 are complete and lint-clean.

**Files** (all in `/home/ubuntu/github/CodingPRD/tasks/task_2558_healthcare_group_purchasing_contract_compliance/`):

| file | lines | content |
|---|---|---|
| `SCAFFOLD.yaml` | 2876 | §1.0–§1.7 — 11 entities, 9 state machines over 8 entities, 2 concurrency rules, 9 calculations (2 dual-variant), 24 validation priorities + 3 declared conflicts, 67 endpoints, 57 error codes, 6 roles (`segregation_of_duties`) |
| `SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 2345 | single key `scaffold_difficulty_design` — 22 instances |
| `SCAFFOLD_CORNER_DESIGN.yaml` | 4237 | single key `scaffold_corner_design` — 85 instances (63 real `test_recipe`s, 22 `excluded_because` stubs) across all nine claim-extraction sections: entities 13, state_machines 20, calculations 13, validations 10, endpoints 6, errors 12, rbac 5, cross_cutting_complexity_layers 5, consistency_model 1 |

All three parse under `yaml.safe_load`; `SCAFFOLD.yaml` contains neither design key, and each design file has exactly one top-level key. No sibling task directory was read at any point.

**Lint verdict (verbatim, final run):**
```
Coverage
  §1.5 endpoints declared:    67
  §1.1 entities declared:     11
  §1.8 instances scanned:     22
  §1.9 instances scanned:     63
  Calls scanned (§1.8+§1.9):  1156

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

**Two scaffold-level fixes were required to get there** (both are genuine scaffold defects the §1.9 pass exposed, not test-side workarounds):
- `Commitment.ytd_leakage_pct` was missing from §1.1 even though the load cascade's hop 3, the reversal compensation and the leakage alert all key on it — added as a computed field with the round-half-up formula and the strict `>` threshold semantics.
- The five FK reverse-reachability reads were declared as nested sub-resources with descriptive path params (`GET /gpo/contracts/{contract_id}/items`, `.../evidence-reviews`, `.../admin-fee-distributions`, `/gpo/commitments/{commitment_id}/compliance-measurements`, `/gpo/distributor-files/{file_id}/purchase-lines`), which check (f) rejects — it only accepts the sub-resource form spelled `{id}`. They were converted to filtered top-level lists (`GET /gpo/contract-items?contract_id=`, `/gpo/clinical-evidence-reviews?contract_id=`, `/gpo/admin-fee-distributions?contract_id=`, `/gpo/compliance-measurements?commitment_id=`, `/gpo/purchase-lines?distributor_file_id=`), which matches the scaffold's `entity_topology: flat` and the five filtered lists it already had, and keeps the endpoint count at 67. Call sites and prose in both design files were updated, and the 404 instance now contrasts a path-id 404 against an unmatched list filter returning an empty 200.

Also worth noting: list endpoints return `<Entity>[]` under `data`, so `$.data.total_count` is not a resolvable capture — the four pagination captures were rewritten as indexed row captures (`$.data[0].classification`, etc.) with row counts asserted in prose.

Coverage checks: all 57 error codes are triggered across §1.8+§1.9, all 85 §1.9 names are unique and disjoint from the 22 §1.8 names, every `excluded_because.difficulty_instance` resolves to a real §1.8 instance, and every `${var}` referenced in an `assert:` is bound by an earlier `captures:` in the same instance. A Step 2 entry was appended to the task's `worklog.md`.

## Step 3: Copy shared files — 2026-09-03T12:07:19.000Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` to `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-03T12:26:30.000Z

Orchestrator truncation check performed independently after the subagent returned: `wc -l` = 514,
`wc -c` = 120323, heading spine = §1, §2 (2.1–2.10), §3 (3.1–3.9), §4, §5; the file ends on the
final complete row of the §5 error table (`| ERR_DISTRIBUTION_BASIS_NOT_COLLECTABLE | 409 |`),
i.e. at a real section boundary, not mid-sentence. No regeneration needed.

Verbatim subagent summary:

PRD generation complete.

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_2558_healthcare_group_purchasing_contract_compliance/workspace/PRD.md` — **514 lines, 120,323 bytes**.

**Truncation check (explicit):** `wc -l` = 514; `tail -40` shows the file ending on the last row of the §5 table, `| `ERR_DISTRIBUTION_BASIS_NOT_COLLECTABLE` | 409 |`. The last heading is `## 5. Error Code Catalogue` (line 454) and the document ends at that completed final section — **not** mid-sentence, and with no audit footer appended. Heading spine verified: §1, §2 (2.1–2.10), §3 (3.1–3.9), §4, §5.

**Coverage counts (PRD vs. scaffold declared):**

| Item | Scaffold | PRD |
| --- | --- | --- |
| Endpoints | 67 | **67** (table rows counted programmatically) |
| Entities | 11 | **11** (all named, all fields backticked) |
| State machines | 9 | **9** — all **49** transitions documented, including the two system-fired `ACTIVE → SUPERSEDED` hops and `REQUAL_REVIEW → ACTIVE` |
| Calculations | 9 | **9** (`tier_activated_price`, `purchase_line_classification`, `compliance_measurement`, `tier_requalification`, `leakage_report`, `evidence_weighted_score`, `admin_fee_accrual`, `distribution_holdback`, `distribution_waterfall`) |
| Validation priorities | 24 | **24** rungs enumerated in ascending order in §2.9, plus the 3 `validation_priority_conflicts` rendered as prose scenarios |
| Error codes | 57 | **57** (§5 table, generated directly from the scaffold's `errors:` block, statuses copied 1:1) |
| Roles | 6 | **6** |

**Hard Contract reports:**

- **CONTRACT 1 — Field-Name Coverage: PASS.** Two independent passes. Pass 1: all **136** `entities[].fields[].name` across 11 entities and all **69** endpoint `input` / path-parameter identifiers appear verbatim inside backticks (0 missing). Pass 2: all 10 inline `output:` dict keys (leakage-report projection: `on_contract_spend_cents`, `leakage_spend_cents`, `unmatched_spend_cents`, `denominator_cents`, `leakage_pct`, `top_items`, …) and all 11 nested-object element identifiers (`member_shares` entries `weight_cents`/`share_cents`, `item_master` entries, `tiers`/`holdback_tiers` entries, `lines[]` entries) present. A residual sweep of every snake_case token in the scaffold left only 77 non-API tokens (scaffold metadata keys like `complexity_profile`, calculation *names* like `distribution_waterfall`, and pseudocode locals like `exact_c`, `frac_c`, `total_weight`) — no entity field or API identifier among them.
- **CONTRACT 2 — Rule Coverage: PASS.** All 24 validation rungs carry their `error_id`, HTTP status and `applies_to` endpoint scope in §2.9 (every rung's error_id is backticked in the PRD). Both `concurrency_rules` are fully specified in §2.6 with write endpoint, OCC field (`expected_commitment_version`, `expected_contract_version`), error_id and 412, each with its own hazard rationale. All 49 transitions and every endpoint `side_effects` entry are documented, including cross-entity cascades (`evidence_endorsed`, `active_commitment_count`, `active_activation_count`, `fee_credit_balance_cents`, `watchlist_status`) with the "recompute at most once per request per affected row" rule. Field-level structured content (types, ranges, defaults, initial values, null-on-birth audit fields) is stated per entity. Sibling-branch symmetry maintained: the three commitment-terminate branches, the two `LOADED`/`PARTIALLY_LOADED`/`REJECTED` load landings, the PRELIMINARY/FINAL measurement variants, the two `ACCRUAL`/`COLLECTED` distribute routes, and the TIER_PRICE/LOCAL_EXCEPTION activation tracks each get equal prose density.
- **CONTRACT 3 — §3 Path Purity: PASS.** 1,152 backtick tokens in §3 (252 unique) scanned: **0** leading-slash tokens, **0** bare HTTP methods, **0** method+path combinations, **0** slash-containing tokens, and **0** raw un-backticked `/gpo/…` strings. All §3 operations are framed as state transitions, role+verb actions, or capability descriptions. §2.9 intentionally carries explicit endpoint paths (§2 is not policed by Contract 3), which is what discharges the `applies_to` requirement without leaking paths into §3.

Also verified: §2.2 is byte-verbatim from `skills/prd-bench-doc-generator/section-2.2-response-structure.md` (placeholders intact); zero fuzzy-quantifier words ("approximately", "roughly", "conservatively", "about", "around", "etc.") anywhere in the document; §4 has exactly 4 columns and §5 exactly 2.

**Hard constraint honored:** neither `SCAFFOLD_DIFFICULTY_DESIGN.yaml` nor `SCAFFOLD_CORNER_DESIGN.yaml` was opened, grepped or referenced. All worked examples in the PRD (75.10%/94.06% dual-variant compliance, TIER_0/TIER_2 two-axis requalification, 8508.5→8509 tier rounding, 35+35=70 per-line fee accrual, 100,200→2505→97,695→58,617 holdback waterfall, the 41,869/16,748 remainder allocation, and the 42/28/70 empty-basis conservation identity) come from `SCAFFOLD.yaml`'s own `calculations[].formula`/`precision`/`note` blocks.

**Two scaffold internal inconsistencies resolved by decision** (worth flagging to the test-suite step so it targets the same reading): (1) `ComplianceMeasurement.status`'s field description implies auto-supersede on re-creation for the same period, which contradicts `ERR_DUPLICATE_MEASUREMENT_PERIOD`; the PRD follows the validation — a `SUPERSEDED` row does not block a new measurement, and superseding happens only via the explicit endpoint. (2) The commitment-terminate endpoint's `side_effects` lists a flat superset of the cascade, while the `election_status` state machine differentiates the `ELECTED` branch (status write only) from the `ACTIVE`/`REQUAL_REVIEW` branches (full activation supersede + counter recomputes); the PRD follows the state machine.

## Step 5: Generate unit tests — 2026-09-03T14:50:00.000Z

Launched concurrently with Step 6 in a single assistant message, so the impl generator started
before `test_suite/` existed (physical isolation). Verbatim subagent summary:

The suite is complete. Final state and findings:

## Output

`/home/ubuntu/github/CodingPRD/tasks/task_2558_healthcare_group_purchasing_contract_compliance/test_helpers/` (9 files, 2,818 lines): `__init__.py` 94, `api_client.py` 387, `api_errors.py` 165, `assertions.py` 339, `constants.py` 191, `factories.py` 346, `fixtures.py` 982, `test_users.py` 135, `types.py` 279.

`.../test_suite/` (conftest + 20 test files, 11,776 lines): `conftest.py` 79; `test_01` 224, `test_02` 317, `test_03` 338, `test_04` 380, `test_05` 376, `test_06` 381, `test_07` 463, `test_08` 438, `test_09` 465, `test_10` 666, `test_11` 766, `test_12` 441, `test_13` 507, `test_14` 1062, `test_15` 968, `test_16` 1173, `test_17` 947, `test_18` 915, `test_19` 475, `test_20` 295.

Finished this session: `test_19_concurrency_tokens_and_threshold_boundaries.py` (cross_cutting, 11 tests — the two OCC-token instances plus `leakage_flag_not_raised_at_exactly_the_threshold`, whose contract is built with `leakage_alert_threshold_pct` omitted from the body so the 15.00 echo really is the PRD default) and `test_20_cascade_visibility_and_settlement_agreement.py` (consistency_model, 7 tests — load cascade readable on the next request, accrual frozen in the create response, the ACCRUAL waterfall 90000/100bps/900/89100/53460, the single share row 53460 on weight 3000000 with `gpo_retained` 36540, the member credit 0 → 53460, and a re-read byte-equal to the write).

## Coverage

280 tests translating **all 85 non-stub design instances**: queue A 22/22 across all 9 `rule_id` blocks; queue B 63/63 (entities 13, state_machines 15, calculations 8, validations 7, endpoints 6, errors 5, rbac 5, cross_cutting 3, consistency_model 1). **Nothing was skipped for PRD-filter reasons** — the only untranslated instances are the 22 `excluded_because:` stubs the design yaml itself defers to a covering instance (5 state_machines, 5 calculations, 3 validations, 7 errors, 2 cross_cutting).

## Verification (no server started, no pytest run, `workspace/implementation/` never touched)

- `python3 -m py_compile` clean on every file in both directories.
- `pyflakes` exit 0 on all 20 test files and all helper modules (only `conftest.py`'s intentional `# noqa: F401` re-exports remain, which pyflakes cannot see).
- AST audit: 280 tests, each with exactly one `Design:` line as the final docstring line, every tag resolving to a real `rule_id`/`section` + `instance.name`; no dual tags, no untagged tests, zero occurrences of the word "scaffold".
- Citations: 670 `PRD §x.y: "..."` quotes, all verifying verbatim (whitespace-normalized) against `workspace/PRD.md`.

**Important tooling finding:** the previous `/tmp/check_citations.py` used the regex `^\s*PRD: "(.+)"$`, which matched only 128 of the 646 citation lines (it missed the `§x.y` label and every quote wrapped across physical lines) — its repeated "missing: 0" was largely vacuous. I rewrote it multiline-aware (`re.S`, whitespace-normalized both sides); the re-audit of the whole suite still shows 0 missing, so no citation ever needed repair.

Also trimmed genuinely dead imports from `test_helpers/fixtures.py` (`Sequence`, `Tuple`, `FLAT_TIER_LADDER`, `FULL_TIER_LADDER`, `HOLDBACK_FLAT`, `HOLDBACK_LADDER`, `TIER_1`, `TIER_2`), and removed the `__pycache__` directories py_compile created.

## Design-yaml defects corrected rather than skipped

1. `match_type: "SUBSTITUTE"` (state_machines #4, validations #3, endpoints `cross_reference_link_requires_both_sides_and_is_unique_each_way`) is not in the PRD enum `EXACT`/`EQUIVALENT`/`MANUAL` → translated as `MANUAL`.
2. calculations #2's `"CONVERSION"` match type → `MANUAL` with `conversion_factor=1.5`.
3. state_machines #8 compared a contract version captured before the election → contract re-read after the election.
4. endpoints `tier_ladder_patch_is_free_on_draft_and_evidence_gated_on_active` omits `requires_clinical_review` (PRD §3.1 defaults it true), which would fail activation on the evidence gate instead of exercising the ladder patch → fixture sets it false with an inline explanation.
5. Helper defect fixed earlier: `XREF_MATCH_TYPES` in `test_helpers/constants.py` corrected to `["EXACT","EQUIVALENT","MANUAL"]`.
6. Wording note (not a defect): the rbac instance `member_materials_manager_cannot_read_another_members_leakage_report` calls both commitments "countersigned ACTIVE" but its setup stops at the election; PRD §3.7 imposes no election-status precondition on the leakage report, so both commitments stay `ELECTED` (which also makes the `lop_status` `NOT_ISSUED` assertion meaningful).

## Step 6: Generate implementation — 2026-09-03T14:50:00.000Z

Verbatim subagent summary:

The implementation is complete. All 67 declared endpoints are live and the app boots cleanly from a fresh process.

## What was finished this session
- `routes/files.py` (229 lines) — endpoints 49–56: distributor-file intake (overlap guard on half-open periods, ignoring `REJECTED`/`REVERSED`), validate/load/reverse wired to `services/ledger.py`, purchase-line list/read. Purchase lines carry only `id`/`created_at` (no `version`).
- `routes/measurements.py` (214 lines) — create (commitment state → OCC 412 → duplicate period → window orientation, then one commitment `version` bump), list, read, `measure` (PRELIMINARY variant), `finalize` (hop 1 final variant preserving `preliminary_compliance_pct`, hop 2 retier, hops 3–5 via `requalification_retier_cascade`), `supersede`.
- `routes/fees.py` (237 lines) — create with once-only `accrued_fee_cents`, list, read, `collect`, `distribute` (basis routing, holdback waterfall, member waterfall, member credits), `reverse` (debits read off the stored `member_shares`).
- `app.py` (98 lines) — blueprint registration, `ApiError`/404/405/HTTPException/500 handlers returning the envelope, a WSGI lock serializing requests, `PORT` env with default 10000.
- Quality fix in `routes/members.py`: nested `item_master` field errors now report dotted paths (`item_master[0].units_per_uom`) instead of placeholder keys.

## Verification
- `python3 -m compileall` clean across all 22 files; endpoint set diffed programmatically against the PRD §4 table: 67 declared, 67 implemented, zero missing, zero extra.
- Full smoke run on self-chosen ports 51843 then 51844 (both killed by their own PID/port; no pattern kill). End-to-end chain exercised: clock → contract → activate → item → member → commitment → LOP issue/sign/countersign → xref approve → tier activation → file intake/validate/load → ledgers → leakage report → requalification → measure → finalize → cascade → fee accrual → distribute → reverse → file reverse.
- Every PRD worked example reproduces exactly: holdback triples (250/2505/97695/58617; 250/3563/138937/83362; 0/0/70/42), the waterfall 41869/16748 summing to 58617, the 75.10 vs 94.06 preliminary/final divergence, and per-line fee rounding 70 (vs the wrong aggregate 69). The live retier cascade superseded the MID tier price at 9200 and minted a `REQUALIFICATION_CASCADE` replacement at TOP/8500 effective from the logical clock date, with both link fields wired and `active_activation_count` recomputed once.
- Audited: no sqlite/file/JSON/tmp persistence, no seeding — all 11 entity dicts start empty.

## Line counts
`app.py` 98, `db.py` 124, `enums.py` 40, `errors.py` 85, `middleware.py` 52, `response.py` 66, `validation.py` 221, `start.sh` 9, `requirements.txt` 1; `routes/`: clock 20, members 147, xrefs 169, reviews 208, measurements 214, files 229, fees 237, contracts 267, commitments 293, activations 312; `services/`: lookup 113, ladders 133, cascade 149, ledger 182, calc 486. Total 3855 lines.

## Step 7: Run tests and iterate — 2026-09-03T15:37:00.000Z

Orchestrator independently verified the sweep artifacts before accepting the exit (per the known
failure mode where a subagent claims a clean sweep with no results files on disk): all 8 of
`workspace/implementation/results.{1..8}.json` exist and each parses to `passed == total == 280`.
Sweep was run under `setsid nohup` so backgrounded rounds could not be reaped by foreground Bash
returns. Step 8 is NOT skipped — Step 7 applied 3 `test_helpers/` fixes (the skip condition
requires zero fixes in every layer).

Verbatim subagent summary:

All 8 parallel rounds now pass 280/280. Exiting clean.

## Summary

**Iterations run:** 2 (each an 8-round parallel `per-test-server` sweep, all rounds run to completion under `setsid`).

- Iteration 1: 275/280 in all 8 rounds — the same 5 failures in every round (deterministic, not flakiness).
- Iteration 2: **280/280 in all 8 rounds.**

**Tests deleted:** none. All 5 failures were verbatim-covered by PRD and uniquely derivable (STEP 1 passed); every one was a `test_helpers/` defect under STEP 2 — no test was weakened, skipped, or relaxed, and no assertion was downgraded.

**Fixes applied to `test_helpers/`:**

1. `test_helpers/api_client.py` — `list_contract_evidence_reviews()` was issuing `GET /gpo/contracts/{contract_id}/evidence-reviews`, a nested route the PRD explicitly forbids. PRD §2.8: *"The resource graph is deliberately **flat**. Only one route in the whole API nests a child under its parent, namely adding an item to a contract's catalog... children are discovered by **filtering a top-level list**, not by reading a nested path: catalog items and evidence reviews and fee distributions are filtered by `contract_id`."* The PRD-faithful implementation correctly 404'd the invented path. Rewritten to `GET /gpo/clinical-evidence-reviews?contract_id=...`, which is what PRD §3.2 publishes (*"Dossiers may be listed filtered by `contract_id` and `status`."*). Fixed `test_12::test_rejecting_the_second_dossier_recomputes_the_flag_to_true_again`.

2. `test_helpers/assertions.py` — `assert_date(value)` was shape-only (1 arg) but four call sites in `test_15` pass an expected date, raising `TypeError` before any assertion ran. Added an optional `expected` parameter that asserts equality on top of the existing `YYYY-MM-DD` shape check. Fixed `test_15::test_a_window_running_past_the_term_is_refused` and `::test_the_last_day_of_the_term_is_inside_it`.

3. `test_helpers/assertions.py` — `assert_cents(value)` had the same defect. Added an optional `expected` parameter asserting integer-cent equality alongside the existing type check. Fixed `test_15::test_the_accepted_local_exception_is_priced_at_the_moment_it_is_drafted` (verified expectation 9600 = `min(9600, 10000)` above the 8200 floor, per PRD §3.6 steps 2–4) and `::test_the_two_tracks_are_separate_ladders_over_the_same_days` (10000 at the 0-bps `TIER_0` rung).

Both `assertions.py` changes are backward-compatible: the five pre-existing 1-arg call sites in `test_10`, `test_17`, `test_18`, `test_19` keep their shape-only behavior, and the 2-arg sites now assert strictly more than before.

**Fixes applied to `implementation/`:** none. No implementation defect was found; every failure traced to the test artifact.

**Note on artifacts:** the 8 `results.*.json` files sit in `/home/ubuntu/github/CodingPRD/tasks/task_2558_healthcare_group_purchasing_contract_compliance/workspace/implementation/` (the mandated `--results-file` path) as evidence of the clean sweep — they are test output, not implementation source, and can be deleted. Storage in the implementation is confirmed in-memory only (no sqlite, file, pickle, or `/tmp` persistence anywhere).

## Step 8: Finalize PRD — 2026-09-03T15:42:00.000Z

Step 8 ran (not skipped: Step 7 applied 3 `test_helpers/` fixes). It concluded that all three
Step 7 items are pure test-artifact defects — an invented nested route the PRD explicitly forbids,
and two 1-arg-vs-2-arg Python helper signatures — so zero PRD edits were warranted and
`PRD_FINALIZED.md` is a byte-identical copy of `PRD.md`. Orchestrator decision: accept this, because
Step 7 recorded zero `implementation/` fixes and zero deletions, which is exactly the shape of a
run whose PRD already determined every behavior the failures touched. The residual-ambiguity work
is Step 9's job, and to guard against the known failure mode where Step 9 returns a byte-identical
file because the scan never really ran, Step 9 is being executed as three sequential
file-partitioned passes over all 22 implementation modules rather than one monolithic scan.

Verbatim subagent summary:

`/home/ubuntu/github/CodingPRD/tasks/task_2558_healthcare_group_purchasing_contract_compliance/workspace/PRD_FINALIZED.md` is produced. **Zero edits were warranted** — all three `<step_7_diff>` items are pure test-artifact defects, not PRD silences or PRD/impl mismatches.

## Line counts
- `PRD.md`: 514 lines / 120,323 bytes
- `PRD_FINALIZED.md`: 514 lines / 120,323 bytes
- Delta: **0 lines, 0.00%** — `diff` is empty, md5 identical (`216192932f42845eb4ac72ad3d3437c8`).

## Changes
None. (No `{section} — {insert|revise}` bullets to report.)

## Per-item pre-edit search log

**Item 1 — `api_client.list_contract_evidence_reviews()` invented nested route.**
- (a) Subject: how a contract's clinical evidence dossiers are discovered, and the `evidence_endorsed` recompute on reject.
- (b) Paths enumerated/read: `implementation/routes/reviews.py` (all 8 handlers — `create_review`, `read_review`, `list_reviews`, `update_scores`, `request_revision`, `resubmit_review`, `endorse_review`, `reject_review`); grepped every route registration for a nested `/gpo/contracts/<id>/…` child collection (only `/gpo/contracts/<contract_id>/items` exists, per `routes/contracts.py`); `services/cascade.recompute_contract_evidence_endorsed` callsites (endorse + reject, both in `reviews.py:187,207`); `test_suite/test_12_transition_side_effects.py:365-441`.
- (c) No wording adjustment — no edit. `list_reviews` (`reviews.py:93-106`) filters on exactly `contract_id` and `status` with `ordered()` `created_at`-ascending paging, which is verbatim what PRD §3.2 ("Dossiers may be listed filtered by `contract_id` and `status`"), §2.8 (flat graph, one nested route) and the §4 table already publish. The impl 404 was correct; the fixture invented a path the PRD forbids. **Pure fixture bug.**

**Item 2 — `assertions.assert_date()` missing `expected` parameter.**
- (a) Subject: the date values `test_15` compares — a contract's echoed `effective_to`, and a created activation's echoed `effective_from`/`effective_to` — plus the containment rule those tests exercise.
- (b) Paths enumerated/read: `implementation/routes/activations.py:45-167` (`create_activation`, full precondition chain); `services/calc.closed_within` (`calc.py:51-52`) and `closed_overlap` (`calc.py:55-57`); `validation.field_date`; every other `closed_within`/`ERR_PERIOD_OUTSIDE_CONTRACT_TERM` callsite (also `routes/commitments.py` for the §3.4 election-start check); the cascade's replacement-window minting in `services/cascade.py`/`ledger.py` that copies `effective_to` and sets `effective_from` from the clock.
- (c) No wording adjustment — no edit. `closed_within` is inclusive on both ends and dates are echoed verbatim in `YYYY-MM-DD`; PRD §2.10 ("both of its inclusive endpoints fall inside the contract's inclusive term", "All dates are ISO calendar dates in `YYYY-MM-DD` form") and §3.6 already determine both assertions uniquely. The failure was a `TypeError` from a 1-arg Python signature called with 2 args — **not a PRD matter at all.**

**Item 3 — `assertions.assert_cents()` missing `expected` parameter.**
- (a) Subject: `computed_price_cents` as minted at DRAFT creation — the local-exception lesser-of ceiling and the plain tier price at a 0-bps rung.
- (b) Paths enumerated/read: `services/calc.derive_activation_price` (`calc.py:83-93`) and `tier_price_cents`/`round_half_up`; **every** `derive_activation_price` callsite, not just creation — `routes/activations.py:142` (request) and the requalification-cascade hops 3/4 that re-derive under the new tier (`services/cascade.py`, `services/ladders.py`); `find_tier`; the reprice path `routes/contracts.py` base-price PATCH (confirmed it does **not** re-derive existing activations); `endorse_activation`/`approve_activation`/`activate_activation` (confirmed none re-derives the price, so "priced at the moment it is drafted" holds); `test_helpers/constants.py` `TIER_ROW_0` (0 bps) and the `build_priced_setup` 10000-cent base / 8200-cent floor.
- (c) No wording adjustment — no edit. `min(requested, tier_price)` then a strict `< floor` clamp, with the single rounding inside `tier_price_cents`, is exactly PRD §3.6 steps 2–4; 9600 and 10000 are both uniquely derivable from the printed rules. Same 1-arg-vs-2-arg signature defect. **Not a PRD matter.**

Zero `implementation/` fixes in Step 7 and zero PRD-silence findings here are consistent: the PRD-faithful implementation was correct on all five failures, and the artifacts were what needed repair.

## Step 9: Complete PRD — 2026-09-03T16:20:00.000Z

Orchestrator decision (recorded because there is no user to consult): Step 9 was executed as three
sequential file-partitioned passes over all 22 implementation modules rather than one monolithic
scan, to guard against the known failure mode where a single scan agent returns a byte-identical
PRD_COMPLETED.md because it never really walked the implementation. Each pass edited the same file
in place, additively, with an explicit instruction never to reset it or delete a prior pass's pinned
behavior (only to widen/soften on conflict). Partitions:
  pass 1 — app/db/enums/errors/middleware/response/validation, routes/clock, routes/contracts,
           routes/activations, services/lookup, services/ladders
  pass 2 — routes/members, routes/xrefs, routes/reviews, routes/commitments
  pass 3 — routes/files, routes/measurements, routes/fees, services/calc, services/cascade,
           services/ledger

Orchestrator verification after pass 3: `PRD_FINALIZED.md` 514 lines / 120,323 bytes → `PRD_COMPLETED.md`
515 lines / 139,675 bytes (+19,352 chars, 115 changed lines under `diff`), md5 distinct from
PRD_FINALIZED.md, all 27 headings intact, file still ending on the final complete row of the §5
error table. Total 66 edits (49 ambiguity-pins, 17 mismatch-revisions). The 8 sweep results files
were re-checked afterwards and still read 280/280 each — Step 9 touched no implementation or test file.

### Pass 1 (verbatim summary)

Done. Verified the file is intact (515 lines vs 514 original — the one added line is a new bullet inside the existing §2.2 error-format bullet list; the file still ends at the final row of the §5 error table).

## Modules scanned (partition — all covered)
`app.py`, `db.py`, `enums.py`, `errors.py`, `middleware.py`, `response.py`, `validation.py`, `routes/clock.py`, `routes/contracts.py`, `routes/activations.py`, `services/lookup.py`, `services/ladders.py`. Cross-read for consistency (not exhaustively scanned): `services/calc.py`, `services/cascade.py`, and every other `routes/*.py` (to confirm the universal claims about `reason` persistence, `query_enum`/`query_string` filter handling, body-FK failure mode, `new_row(versioned=…)`, and `ERR_TIER_CODE_UNKNOWN` reachability).

## Counts
21 edits: **15 ambiguity-pins**, **6 mismatch-revisions**.

## Changes
- §2.1 — revise — mismatch — `X-User-ID` also rejected when whitespace-only (`middleware.py:44`).
- §2.2 success bullets — insert — ambiguity — `api_request_id` is `req_` + exactly 20 uppercase-alnum chars (`response.py:12-14`).
- §2.2 error header — revise — mismatch — error envelope covers 4xx **and 5xx** (`app.py:80-84`).
- §2.2 error bullets — insert (new bullet) — ambiguity — `ERR_NOT_FOUND`/404, `ERR_METHOD_NOT_ALLOWED`/405, `ERR_INTERNAL`/500 use the same envelope and are outside the §5 catalogue (`app.py:63-84`).
- §2.3 — insert — ambiguity — `offset` unbounded; empty param = absent; non-integer / out-of-range → `ERR_INVALID_REQUEST` 400; ties on `created_at` broken by creation order (`validation.py:169-189`, `db.py:118-121`).
- §2.4 — insert — ambiguity — clock echoes the raw string verbatim, accepted ISO forms (optional seconds/fraction, `T` or space, `Z`/offset/no zone→UTC), role header still required (`db.py:17-37`, `routes/clock.py:16-20`).
- §2.4 — revise — ambiguity — every `created_at`/`updated_at` and every envelope `api_request_timestamp` also read the logical clock (`db.py:97-108`, `response.py:19-24`).
- §2.5 — insert — ambiguity — two-decimal percentages serialize as bare JSON numbers (15.00 → `15.0`) (`response.py:27-34`).
- §2.7 — insert — ambiguity — requests are processed strictly one at a time (`app.py:39-50`).
- §2.8 discovery — insert — ambiguity — filters conjunctive/optional; enum filters → 400 on unknown value; identifier/code filters matched literally with no existence check (`validation.py:192-205`, all `routes/*` list handlers).
- §2.8 body FKs — insert — ambiguity — declaration order is the fixed `BODY_FK_ORDER`, not JSON key order; absent/null/empty/non-string FK is a rung-6 400, never a 404 (`services/lookup.py:88-113`).
- §2.9 rung 6 — insert — ambiguity — `null` counts as absent; absent body = empty object; non-object body → 400; ints strict (no bool/float) while decimals accept decimal strings; scalars validated before ladders, `tiers` before `holdback_tiers` (`validation.py:17-120`, `routes/contracts.py:57-85`).
- §2.9 rung 7 — revise — mismatch — `ERR_CONTRACT_ITEM_NOT_ACTIVE` also fires on price-activation create and on double-delist; item check sits right after the contract check (`routes/activations.py:91-94`, `routes/contracts.py:281-284`).
- §2.9 rung 16 — revise — mismatch — `ERR_TIER_CODE_UNKNOWN` applies only to commitments and price-activations; ladder shape guarantees it cannot fire on tiers-PATCH or contract-activate (`services/ladders.py:71-83`, `routes/contracts.py:134-170`).
- §3.1 registration — insert — ambiguity — bad term order and duplicate `contract_code` are both `ERR_INVALID_REQUEST` 400, term checked first (`routes/contracts.py:79-83`).
- §3.1 tier ladder — insert — ambiguity — `tiers` mandatory; entry field ranges (`tier_code` 1–40, volume ≥ 0, `min_compliance_pct` 0.00–100.00/2dp); entry- and container-level faults are `ERR_INVALID_REQUEST`, `ERR_INVALID_TIER_LADDER` reserved for ladder-level rules, entry checks first (`services/ladders.py:24-93`).
- §3.1 holdback ladder — insert — ambiguity — absent/null `holdback_tiers` is the sole `ERR_INVALID_REQUEST` case, everything else `ERR_INVALID_HOLDBACK_LADDER`; tier ladder validated first (`services/ladders.py:96-133`, `routes/contracts.py:84-85`).
- §3.1 suspend — revise — mismatch — `reason` is validated as a string but not persisted (`routes/contracts.py:178`).
- §3.1 catalog create — insert — ambiguity — no contract-status precondition (DRAFT/ACTIVE/SUSPENDED all allowed); floor>base and duplicate `vendor_item_number` are 400s, price relation first (`routes/contracts.py:189-208`).
- §3.1 reprice/delist — insert — ambiguity/mismatch — non-positive price also yields `ERR_BASE_PRICE_BELOW_FLOOR` after the version check; DELISTED lines stay repriceable; delist `reason` not persisted; double delist → `ERR_CONTRACT_ITEM_NOT_ACTIVE`; already-created activations on a delisted line still endorse/approve/activate (`routes/contracts.py:251-287`, `routes/activations.py:249-292`).
- §3.6 request chain — revise — mismatch — role-and-scope branch moved ahead of the commitment/mismatch/contract checks; FK resolution order and 400-for-missing-FK pinned; delisted-item check and the tier-code check inserted before the window/containment/overlap rules; `requested_price_cents` ≤ 0 is a 400; step 1 of the derivation cross-linked to that ordering (`routes/activations.py:45-144`).
- §4 intro — insert — ambiguity — trailing slash ignored in path matching (`app.py:56`).

## Deliberately left unpinned
- `JSON_SORT_KEYS = False` (response key order): not meaningfully observable and pinning it would over-constrain.
- Sub-millisecond truncation in `format_timestamp` (microseconds floored to 3 digits): PRD already fixes three fractional digits; the extra precision case is a far edge and better left under-determined.
- `field_decimal` accepting negative/zero via 409 vs 400 on paths outside my partition (evidence scores, conversion factor) — left to passes 2/3.
- Rung 7's list of ACTIVE-contract-requiring operations beyond contracts/activations (distributor files, fee accrual) — verified consistent but owned by other passes.

### Pass 2 (verbatim summary)

Pass 2 complete. PRD_COMPLETED.md edited in place: 515 lines / 135,758 bytes (was 129,516), still ending at the final `ERR_DISTRIBUTION_BASIS_NOT_COLLECTABLE | 409` row of the §5 table.

## Modules scanned (partition — all four covered end to end)
- `implementation/routes/members.py` (147 ln) — all 5 endpoints, `parse_item_master`, suspend guard.
- `implementation/routes/xrefs.py` (169 ln) — all 5 endpoints, `_duplicate_guard`.
- `implementation/routes/reviews.py` (208 ln) — all 7 endpoints, `_parse_scores`/`_apply_scores`.
- `implementation/routes/commitments.py` (293 ln) — all 10 endpoints (create/read/list, LOP issue/sign/countersign/void, open-requalification, terminate, leakage-report).

Cross-read for consistency: `db.py`, `enums.py`, `middleware.py`, `response.py`, `validation.py`, `services/lookup.py`, `services/cascade.py`, `services/calc.py`, `routes/activations.py`, `routes/contracts.py` (plus a body-parse census of every route in the tree).

## Counts
**22 edits: 16 ambiguity-pins, 6 mismatch-revisions.**

## Changes
- §2.7 — revise — mismatch — `active_commitment_count` recompute triggers: PRD said countersign / **void** / terminate; impl recomputes on election, countersign, and termination out of `ACTIVE`/`REQUAL_REVIEW` only — void/issue/sign never do, nor does terminating from `ELECTED` — `commitments.py:120,207,258`
- §2.9 rung 3 — revise — mismatch — "exactly five operations" → six (adds `PATCH /gpo/members/{member_id}/item-master`), plus which of the six compare before resolution (commitments/xrefs/item-master) vs. after (`lop/sign`, leakage-report → 404 first; price-activations → after rung 5 and 6) — `members.py:134`, `commitments.py:172,281`, `activations.py:74`
- §2.9 rung 6 — insert — ambiguity — an action endpoint declaring no body field never reads the body, so an invalid-JSON body is ignored there (enumerated the 10 such endpoints) — `xrefs.py:137`, `reviews.py:175`, `commitments.py:154,190`
- §2.9 rung 7 — revise — mismatch — the `DRAFT`-or-`ACTIVE` admission also governs `POST /gpo/clinical-evidence-reviews`, which rung 7's endpoint enumeration omitted — `reviews.py:65`
- §3.2 — insert — ambiguity — review created with `endorsed_by_user_id` null — `reviews.py:79`
- §3.2 — insert — ambiguity — request-revision tests `UNDER_REVIEW` **before** the revision budget, so `REVISION_REQUESTED`@round 2 reports `ERR_INVALID_REVIEW_STATE` — `reviews.py:131`
- §3.2 — revise — ambiguity — resubmit: all three scores mandatory; `summary` optional and, when omitted/null, leaves the stored narrative unchanged — `reviews.py:151,155,163`
- §3.2 — insert — ambiguity — rejection leaves `endorsed_by_user_id` null; the `reason` on request-revision/reject must be a string but is stored nowhere — `reviews.py:198,204`
- §3.3 — insert — ambiguity — item-master entry shapes (`member_item_number`/`description` min 1, no max; `units_per_uom` ≥ 1), array mandatory, extra entry keys dropped; duplicate `member_code` and duplicate `member_item_number` are `ERR_INVALID_REQUEST` (400), code-uniqueness checked last — `members.py:35-66,75-79`
- §3.3 — insert — ambiguity — item-master replacement array mandatory, same rules as registration, and no member-status precondition (a `SUSPENDED` member may still curate) — `members.py:130-137`
- §3.3 — insert — ambiguity — suspend only from `ACTIVE` (second suspend → `ERR_MEMBER_NOT_ACTIVE`); `reason` string-but-not-persisted; terminal — `members.py:140-147`
- §3.4 — revise — **mismatch** — election precondition order: scope first (pre-resolution), then `contract_id`→`member_id` resolution, member ACTIVE, contract ACTIVE, **duplicate before tier-code** (PRD had tier before duplicate), period, volume; matches the §2.9 rung 15-before-16 ladder — `commitments.py:46-99`
- §3.4 — insert — ambiguity — payload shapes: `elected_tier_code` 1–40 chars, `committed_volume_units` a bare JSON integer with no range bound of its own — `commitments.py:61-63`
- §3.4 — revise — housekeeping — "lowest-priority of the seven" → "of them all" (list is no longer seven items)
- §3.4 — insert — ambiguity — issue checks `lop_status` before `election_status`, so re-issuing an `ISSUED`/`SIGNED`/`COUNTERSIGNED` letter reports `ERR_INVALID_LOP_STATE` — `commitments.py:157-167`
- §3.4 — insert — ambiguity — countersign's election refusal is named: `ERR_COMMITMENT_NOT_ELECTED`, reachable via terminate-from-`ELECTED` — `commitments.py:194`
- §3.4 — insert — ambiguity — void reads no `election_status` precondition at all, so a `TERMINATED` commitment's `ISSUED`/`SIGNED` letter is still voidable; `reason` not persisted — `commitments.py:212-224`
- §3.4 — insert — ambiguity — a second termination is refused with `ERR_COMMITMENT_NOT_ACTIVE`; terminate/open-requalification `reason` not persisted — `commitments.py:249-253`
- §3.5 — insert — ambiguity — proposal `member_item_number` is 1–40 chars (narrower than the item-master entry it must match); `conversion_factor` has no upper bound — `xrefs.py:68-72`
- §3.5 — revise — mismatch — proposal precondition order: scope on the declared `member_id` before any fetch, then `member_id`→`contract_item_id` resolution; the "parent contract" is the one owning the named item, there being no body `contract_id` — `xrefs.py:55-79`
- §3.5 — insert — ambiguity — mapping born with `approved_by_user_id` and `reject_note` null; approval re-evaluates **only** uniqueness (contract may be `SUSPENDED`, item `DELISTED`, number gone from the master); rejection leaves `approved_by_user_id` null — `xrefs.py:101-107,137-152,163`
- §3.7 (report) — insert — ambiguity — `from_date`/`to_date` are mandatory query params (missing/empty/non-date → `ERR_INVALID_REQUEST`); only a `MemberMaterialsManager` caller is scope-checked; the projection carries no `id`/`created_at`/`updated_at`/`version` — `commitments.py:281-297`, `calc.py:359-369`

## Deliberately left unpinned
- Which of the three evidence scores is reported first when several are malformed — every path yields the same `ERR_INVALID_REQUEST` identifier, so it is unobservable.
- `xrefs.py:250` residual redundancy "the catalog item must exist and be `ACTIVE`" after my inserted resolution clause — harmless duplication, not a contradiction; left alone under the minimal-change rule.
- Countersign retaining `signer_name` — PRD only ever says issue and void clear it, so silence here is not ambiguity.
- `PATCH .../scores` having no segregation check — PRD's "the revising reviewer" already admits any `ClinicalReviewer`.
- Members' `watchlist_status` / `fee_credit_balance_cents` writers — driven by `files.py`/`fees.py`, outside my partition.

## Pass 1 integrity
All 21 pass-1 edits verified still present (spot-checked 25 distinctive markers — whitespace-`X-User-ID`, 20-char `api_request_id`, `ERR_METHOD_NOT_ALLOWED`, offset unbounded, verbatim `current_utc`, `15.0`/`0.0` serialization, single-threaded cascades, filter semantics, rung-6 null/body rules, delist-twice, rung-16 cannot-fire, contract term/code order, `tiers`/`holdback_tiers` mandatory, contract `reason` not persisted, item add has no contract-status gate, base-price positivity via 409, `requested_price_cents` null-counts-as-omitted, activation resolution chain, trailing-slash — each found exactly once). My only touches inside pass-1 text were widenings (rung 3 five→six, rung 6 no-body clause, rung 7 adding the reviews endpoint); no pinned behavior was removed.

### Pass 3 (verbatim summary)

Scan complete. All 23 edits applied surgically with Edit; file integrity verified.

## Modules scanned (partition — all six covered exhaustively)
- `routes/files.py` (229 L) — intake, validate/load/reverse, both list endpoints, purchase-line reads
- `routes/measurements.py` (214 L) — create, measure, finalize, supersede, lists
- `routes/fees.py` (237 L) — create/accrue, collect, distribute, reverse, lists
- `services/calc.py` (486 L) — rounding, intervals, tier price, evidence, classification lookups, aggregation, qualified tier, leakage report, accrual, holdback, member waterfall
- `services/cascade.py` (149 L) — three counter recomputes, dedupe, termination supersede, requalification retier cascade
- `services/ledger.py` (182 L) — validate, classify, load 3-way landing, 4 ledger hops, 3-hop reversal

Cross-read for consistency: `validation.py`, `db.py`, `response.py`, `errors.py`, `middleware.py`, `enums.py`, `services/lookup.py`, `services/ladders.py`, and the reviews/xrefs/contracts/commitments/activations/members routes.

## Counts: 18 ambiguity-pins, 5 mismatch-revisions

- §2.8 — revise — mismatch — distributor-file filter list gains `distributor_code` — `routes/files.py:151`
- §2.9 rung 6 — revise — ambiguity — decimals are range-checked at this rung, so an out-of-range evidence score and a zero/negative `conversion_factor` are 400s, never 409 — `validation.py:118`, `routes/reviews.py:36`, `routes/xrefs.py:74`
- §2.9 rung 6 — revise — mismatch — body-less action list gains measure, finalize, distribute — `routes/measurements.py:151,170`, `routes/fees.py:150`
- §2.6 — insert — ambiguity — `expected_commitment_version` is an integer ≥ 0; negative is rung-6 400, not 412 — `routes/measurements.py:64`
- §3.3 — revise — ambiguity — the two §3.7 hops are `watchlist_status`'s only writers; `fee_credit_balance_cents` is non-negative by construction (debits reverse recorded credits), not by clamping — `services/ledger.py:129,167`, `routes/fees.py:196,222`
- §3.7 — revise — ambiguity — file-submission check order rewritten (shape incl. `lines` → member status → contract status → window → overlap); the old sentence listed `lines` *after* the window check, contradicting impl — `routes/files.py:69-107`
- §3.7 — insert — ambiguity — the `REJECTED` landing leaves `loaded_at` null — `services/ledger.py:75`
- §3.7 — insert — ambiguity — governing-activation ranking has a final creation-order tiebreak after `created_at` — `services/calc.py:196`
- §3.7 hop 3 — insert — ambiguity — a load can only raise `leakage_flag`; only a file reversal lowers it — `services/ledger.py:120`
- §3.7 hop 4 — insert — ambiguity — the member row is rewritten (version+1) on every rise even if already `WATCHLIST`; no rise means no member write — `services/ledger.py:128`
- §3.7 reversal — insert — ambiguity — compensation targets the commitment recorded at load; a load that found none skips all three hops — `services/ledger.py:141`
- §3.7 reversal — insert — ambiguity — an already-`NONE` member is not written at all — `services/ledger.py:167`
- §3.7 reversal — insert — ambiguity — `line_count`/`accepted`/`rejected`/`loaded_at` preserved; `reason` must be a string — `services/ledger.py:178`, `routes/files.py:186`
- §3.8 — revise — mismatch — `REJECTED` files are excluded by both variants (sentence omitted the status) — `services/calc.py:236`
- §3.8 — insert — ambiguity — measuring reads no commitment-status precondition; only finalize demands `REQUAL_REVIEW` — `routes/measurements.py:151`
- §3.8 — insert — ambiguity — a `basis_empty` final measurement qualifies the default rung and really does retier down — `services/calc.py:299`, `routes/measurements.py:196`
- §3.8 hop 3 — insert — ambiguity — minted replacements carry null `endorsed_by_user_id`/`approved_by_user_id`/`deny_note` and `version` 1 (hop 4 alike) — `services/cascade.py:80`
- §3.8 hop 4 — revise — mismatch — *every* ACTIVE local exception for the pair is superseded, in creation order (was "if one exists") — `services/cascade.py:135`
- §3.8 supersede — revise — ambiguity — `reason` must be a string and is persisted nowhere — `routes/measurements.py:206`
- §3.9 — insert — ambiguity — remainder ranking's final tiebreak is member creation order — `services/calc.py:455`
- §3.9 — insert — ambiguity — `member_shares` ordering's final tiebreak likewise — `services/calc.py:460`
- §3.9 reversal — revise — ambiguity — `reason` must be a string when present — `routes/fees.py:216`
- §4 — revise — mismatch — distributor-files table row gains `distributor_code` — `routes/files.py:151`

## Deferred items
- **(a) `field_decimal` negative/zero, 409-vs-400** — resolved at rung 6: `field_decimal` enforces range inline, and `conversion_factor`'s `<= 0` test raises `bad()`, so both are `ERR_INVALID_REQUEST` 400. Consistent with pass 1's existing §3.1 claim that an out-of-range `min_compliance_pct` is also a plain 400.
- **(b) rung 7's ACTIVE-contract operations** — pass 1's line already names `POST /gpo/distributor-files` and `POST /gpo/admin-fee-distributions`, and both match impl (`files.py:85`, `fees.py:45`). I verified nothing else in my partition reads contract status (validate/load/reverse a file, all four measurement endpoints, collect/distribute/reverse a settlement), so the list stays exhaustive — **no edit needed**.
- **(c) pass 2's `watchlist_status` / `fee_credit_balance_cents` writers** — resolved by the §3.3 revision plus the two §3.7 asymmetry pins (rise always writes, fall skips an already-`NONE` member).

## Deliberately left unpinned
Accrual's visit order (`purchase_date`, `created_at`, seq) — the sum is order-independent and unobservable; unreachable defensive branches (missing contract/tier/member rows, `leakage_pct`'s `total <= 0` guard, `qualified_tier_code` with a null contract); error *message* text and the `lines[i].field` labels (only `error_id`+status are contractual); the absence of a max length on `lines`; and whether an optional `reason` may be the empty string.

## Integrity
`wc -l -c` = **515 lines / 139,675 bytes**; `tail -c 300` still ends at `| ERR_DISTRIBUTION_BASIS_NOT_COLLECTABLE | 409 |`. Ten distinctive pass-1/pass-2 phrases spot-checked and still present; diff vs `PRD_FINALIZED.md` is 58 changed lines with zero deletions of prior-pass content — my 23 edits landed on 20 lines, several already rewritten by earlier passes, and every prior pinned behavior was preserved or widened, never removed.

---

## Pipeline complete — 2026-09-03T16:22:00.000Z

All nine steps finished. Final artifacts: `SCAFFOLD.yaml` + two design indices, `workspace/PRD.md`,
`workspace/PRD_FINALIZED.md`, `workspace/PRD_COMPLETED.md`, `test_helpers/` (9 files), `test_suite/`
(conftest + 20 files, 280 tests), `workspace/implementation/` (22 modules, 67 endpoints) and the
eight `results.{1..8}.json` from the final clean 8-round `per-test-server` sweep (280/280 each).
