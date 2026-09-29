# Worklog — task_2623_brand_safety_ad_verification_operations

## Step 1: Create task directory — 2026-09-03T20:59:00.000Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2623_brand_safety_ad_verification_operations` and `.../workspace`. Index 2623 was pre-assigned by the orchestrating prompt (no ./tasks/ scan, no auto-allocation) because up to 32 pipelines run concurrently on this host and auto-allocation would collide.

## Step 2: Generate scaffold — 2026-09-03T23:05:00.000Z

All three artifacts are complete, mutually consistent, and lint-clean.

## Output (all under `/home/ubuntu/github/CodingPRD/tasks/task_2623_brand_safety_ad_verification_operations/`)

```
  3146 SCAFFOLD.yaml                    (160,779 bytes)
  2088 SCAFFOLD_DIFFICULTY_DESIGN.yaml  (140,846 bytes)
  5720 SCAFFOLD_CORNER_DESIGN.yaml      (378,946 bytes)
 10954 total
```
`ls -la` also shows the pre-existing `worklog.md` (432 bytes) and empty `workspace/`. Every file was built by incremental `cat >>` heredoc appends with a `yaml.safe_load` re-parse after each chunk; all three parse cleanly. Top-level keys: `SCAFFOLD.yaml` -> scenario / domain_name / api_prefix / complexity_profile / response_envelope / entities / state_machines / concurrency_rules / calculations / validations / endpoints / errors / roles (neither `scaffold_difficulty_design` nor `scaffold_corner_design` present); the other two files each have exactly their one required top-level key.

## Lint verdict (verbatim, final run)

```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           .../SCAFFOLD.yaml
  Difficulty design:  .../SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      .../SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    54
  §1.1 entities declared:     13
  §1.8 instances scanned:     21
  §1.9 instances scanned:     64
  Calls scanned (§1.8+§1.9):  1143

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

## Scaffold shape

13 entities, 12 state machines (MeasurementBatch is two parallel dimensions), 2 concurrency rules, 10 calculations (2 dual-variant), 35 ordered validations, 54 endpoints, 67 errors, 7 roles. `complexity_profile`: layers cascading_side_effects / dual_variant_calculation / optimistic_concurrency / version_pinning_on_approval, flat topology, parallel state shape, segregation_of_duties role model, immediate consistency.

§1.8: 21 instances across 9 dimension groups. §1.9: 81 instances — 64 with full `test_recipe`, 17 `excluded_because` stubs, each citing a §1.8 instance that exists by name (verified programmatically). Section counts: entities 12, state_machines 18, calculations 11, validations 13, endpoints 6, errors 10, rbac 5, cross_cutting_complexity_layers 5, consistency_model 1.

## Verification done beyond the lint

- **Error coverage**: all 67 catalog ids are triggered by at least one §1.8/§1.9 instance; zero uncovered, zero phantom ids referenced. The last gap, `ERR_STALE_PAGE_VERSION`, is closed by the new `page_occ_token_advances_on_every_write_that_touches_the_page` instance.
- **Placeholder closure**: scripted check over all 85 instances — every `${...}` used in a payload, path or assert is defined by a `captures:` in the same instance. 0 gaps.
- **Grounds resolvability**: every `grounds` reference resolves to a real entity/field, state-machine transition or dimension, calculation name, `validations.priority_N`, error id, endpoint or role. 0 dangling.
- **No duplicate instance names** anywhere in §1.9.

## Two scaffold fixes made this session

1. `state_machines.RefundClaim.terminal_states` listed `APPROVED` while also declaring `APPROVED -> REVERSED` via `POST /refund-claims/{id}/reverse` — a self-contradiction that would have made any terminal-lockdown test unsatisfiable. Now:
   `terminal_states: [REJECTED, REVERSED]   # APPROVED is settled but not terminal: POST /refund-claims/{id}/reverse still applies`
   A sweep confirmed no other state machine has a terminal state with outgoing transitions.
2. A `publisher_quality_index` assert in the consistency instance was recomputed from the actual constants: index `97.00` / band `PREFERRED` (my draft had 82.00 / a non-existent band `LOW_RISK`; the declared bands are PREFERRED / STANDARD / WATCHLIST / SUSPENDED_QUALITY).

## Final content added after the break

`cross_cutting_complexity_layers` (2 real OCC instances for both §1.2.1 rules plus stubs for cascading_side_effects, dual_variant_calculation and version_pinning_on_approval), `consistency_model` (1 `immediate` instance proving certify publishes publisher counters, scorecard and campaign rollup inside the same request), and two extra `validations` instances added to close the last two unused Table-4 pattern rows: `revised_tier_guard_applies_only_to_the_overturned_branch` (conditional_validation — the full missing/equal/worse/better grid on the overturn arm plus the stray-field arm on the uphold) and `claim_window_check_consumes_the_dereferenced_batch_set` (cascading_validation — priority 5 -> 15 -> 33, showing the 30-day window cannot be evaluated until batch_ids is dereferenced and scoped).

The hard constraint was respected throughout: no sibling `task_*/` directory was listed, globbed, grepped or read at any point; every fact came from the scenario text, the scaffold-generator skill's specification, and this task's own SCAFFOLD.yaml.

## Step 3: Copy shared files — 2026-09-03T23:06:00.000Z

Copied ./INSTRUCTION.md -> workspace/INSTRUCTION.md (1424 bytes).

## Step 4: Generate PRD — 2026-09-03T23:22:00.000Z

The PRD is complete and all three Hard Contracts verify PASS.

**Output:** `workspace/PRD.md` — 481 lines, written incrementally (1 `Write` + 7 `cat >>` heredocs; no truncation).

**Termination check:** file ends at line 481 with `| \`ERR_CREDIT_CAP_EXCEEDED\` | 409 |` followed by a trailing newline — the final row of the completed §5 error table (67/67 rows present). Not mid-sentence. Section skeleton is complete: §1 Introduction, §2 (2.1–2.11), §3 (3.1–3.9), §4 Endpoint Definitions, §5 Error Code Catalogue.

**CONTRACT 1 (Field-Name Coverage): PASS** *(run twice, identical results)*
- `entities[].fields[].name`: 133 required / 133 present / 0 missing
- `request_body` / `input` names (non-GET): 69 / 69 / 0
- `query_params` (GET inputs): 33 / 33 / 0
- `path_params`: 1 / 1 / 0
- computed-read `output` fields: 18 / 18 / 0

(The earlier "everything missing" avalanche was a harness bug, not a PRD defect: a backtick regex mis-paired across two json fences in §2.2, inverting the membership test. Fixed by stripping fenced blocks and forbidding newlines inside a token.)

**CONTRACT 2 (Rule Coverage): PASS**
- Validations: 35/35 present in §2.8 as a priority-ordered list, each with rule, error id, HTTP status and `applies_to` scope (all 35 have an explicit scope). The three generic scaffold placeholders `ERR_<ENTITY>_NOT_FOUND` (priorities 4, 5) and `ERR_INVALID_<ENTITY>_STATE` (priority 7) are expanded to their concrete per-entity ids in the §5 catalogue.
- State machines: 12 machines, 53/53 transitions covered (51 as explicit `FROM -> TO` pairs; the two Publisher transitions `RESTRICTED -> ACTIVE` and `ACTIVE -> DELISTED` are covered in §3.1 prose). All 43 distinct state literals present.
- Concurrency: 2/2 OCC rules in §2.7 (`expected_page_version` / `ERR_STALE_PAGE_VERSION`, `expected_campaign_version` / `ERR_STALE_CAMPAIGN_VERSION`, both 412) with write endpoint, field and status.
- Calculations: 10/10 described including both dual variants (gross vs net impression basis; post-bid page-level vs pre-bid domain rollup). Every numeric constant appearing in the calculation blocks is present; the only literals absent verbatim are `500000`/`555000`/`499500`/`471750`/`55500`, written with thousands separators in the §3.9 non-circularity worked example, and `4004`, spelled out as `1501` + `2503` -> 3503 vs 3504 in the §2.6 rounding-divergence example.
- Field-level defaults: 92/92 default values stated (`latest_category_codes` `[]` is stated as "empty").
- Enum literals: 97/97 present. Errors: 67/67. Cascades: all four multi-hop chains written out hop-by-hop (methodology suspension; quarantine -> restriction -> list stale -> segment stale; MFA-flag flip -> restriction -> cascade; appeal overturn -> remedy -> batch re-tier -> claim auto-reject).
- Sibling-branch symmetry preserved: CONFIRM/OVERRIDE, UPHELD/OVERTURNED, certify->CERTIFIED/QUARANTINED with disjoint side-effect sets, IVT confirm/retract, claim approve/reject/reverse.
- §4 table: 54/54 endpoints, exact method+path, and authorized-role lists match the scaffold `roles` for every row (0 mismatches). All 13 scaffold `201` endpoints are resource-creating POSTs, consistent with the stated 201-vs-200 rule.

**CONTRACT 3 (§3 Path Purity): PASS**
- §3 spans 168 lines / 66,678 chars; 1,131 backtick tokens (375 unique).
- Tokens starting with `/`: 0. Bare HTTP-method tokens: 0. Method+path tokens: 0. Raw (unbackticked) method+path or path strings in §3 prose: 0.
- The only token containing a slash is `https://`, a `url` field format constraint in §3.3, not an endpoint reference.

Constraints honoured: `SCAFFOLD_DIFFICULTY_DESIGN.yaml` and `SCAFFOLD_CORNER_DESIGN.yaml` were never opened, grepped, or referenced; no sibling task directory was read.

**Orchestrator verification of the known truncation failure mode:** independently ran `wc -l` (481), `wc -c` (108,998), `grep -n '^#'` (28 headings: §1, §2.1–2.11, §3.1–3.9, §4, §5 all present in order), and `tail -12`. The file ends on the last row of a complete §5 table with 67 `ERR_` rows — a real section boundary, not mid-sentence. Also grepped for the difficulty instruction ("harder than expert", "expert level"): 0 hits, so it did not leak into PRD.md.

## Step 5: Generate unit tests — 2026-09-04T00:10:00.000Z

Stage 2 is complete and audited clean.

## Outputs (both at the TASK ROOT, nothing under `workspace/`)

`ls -d` confirms `.../test_helpers` and `.../test_suite`; `ls -a workspace/` shows only `.`, `..`, `INSTRUCTION.md`, `PRD.md` — no leak, and `workspace/implementation/` was never touched.

**test_helpers/ (9 files, 2299 lines)**: `__init__.py` 139, `api_client.py` 236, `api_errors.py` 148, `assertions.py` 288, `constants.py` 113, `factories.py` 231, `fixtures.py` 527, `test_users.py` 90, `types.py` 526.

**test_suite/ (20 files, 13541 lines)**: `conftest.py` 72; `test_01_dual_basis_variants` 682, `test_02_credit_money_arithmetic` 368, `test_03_lifecycle_cycles_and_dimensions` 560, `test_04_multi_hop_cascades` 712, `test_05_rejection_precedence` 431, `test_06_threshold_boundaries` 659, `test_07_cross_entity_preconditions` 401, `test_08_temporal_window_rules` 400, `test_09_compensating_operations` 476, `test_10_entity_contracts` 1044, `test_11_batch_and_claim_state_transitions` 913, `test_12_review_and_appeal_transitions` 775, `test_13_computed_figures` 1033, `test_14_referential_and_window_validations` 722, `test_15_validation_ordering_and_lapse` 834, `test_16_endpoint_contracts` 859, `test_17_error_catalogue` 1430, `test_18_roles_and_ownership` 597, `test_19_occ_and_consistency` 574. Grand total 15840 lines.

## Verification
- **181 test functions, 182 collected items** (one parametrized x2). `PYTHONPATH=. pytest test_suite --collect-only -q` collects all of them, so every `test_helpers` import resolves.
- `ast.parse` clean on all 29 generated files; no duplicate test-function names within any file.
- **Design-tag audit: no problems.** Exactly 181 `Design:` lines for 181 tests (one per test, last docstring line); zero dangling names, zero wrong rule_id/section, zero stub translations, zero dual/untagged tests.
- **Coverage: 21/21 difficulty instances with >=2 tests; 64/64 non-stub corner instances with >=1 test.** All 17 `excluded_because:` stubs untranslated with no placeholders.
- Zero `pytest.mark.skip` / `skipif` / `xfail` / `pytest.skip(` anywhere.
- Every `PRD: "..."` citation verified as a verbatim (whitespace-flattened) substring of `workspace/PRD.md`, each >=8 words.
- No "scaffold"/design-index vocabulary in any comment or docstring outside the mandated tag line.

## Helper fixes applied after the sub-agents finished
Recurring friction they had to work around inline: `setup_ingested_batch` forwarded `window_start`/`window_end` positionally and also splatted `**overrides`, so any window override raised `TypeError: got multiple values for keyword argument`. Made it `pop` `window_start`, `window_end`, `page_id` and `methodology_version_id` from overrides (defaults unchanged), gave `batch_window` a `date=` parameter, and added `read_methodology_version` (exported from `test_helpers`). All additions are optional-parameter-only; collection still yields 182 tests.

## Gaps deliberately left as gaps (PRD-first filter)
- Ten of the twelve typed not-found ids in `errors/every_aggregate_answers_its_own_typed_not_found` are named only in the §5 table, never in prose — only `ERR_INVENTORY_LIST_NOT_FOUND` and `ERR_MEASUREMENT_BATCH_NOT_FOUND` were asserted. Same reason dropped `ERR_CAMPAIGN_NOT_FOUND` from the claim-intake ladder and `ERR_PUBLISHER_NOT_FOUND` from the flat-topology FK instance (both instances still covered by their prose-grounded halves).
- `coverage_rate == null` on an unscored batch, and `created_at` pinned to the logical clock, were not asserted: the PRD pins neither.
- `effective_tier` is asserted only where the tier gate actually runs.

## Design-index defects found and corrected against the PRD
- `boundary_precision_check/coverage_rate_exactly_at_floor...` asserts `viewability_rate == 0.7`; the PRD formula gives 1.0000 for that fixture (7000 of 7000 measurable, both DISPLAY thresholds cleared). Test asserts 1.0.
- `errors/decertified_batch_credits_nothing...` was unreachable as written (decertifying the only certified batch yields `coverage_status` UNKNOWN, and remediation fires only on BELOW_TARGET); rebuilt with two abutting versions so the campaign genuinely reaches UNDER_REMEDIATION.
- Same instance family: a future-window probe would have been pre-empted by the earlier-priority `ERR_BATCH_WINDOW_COLLISION`; retargeted to a second page.
- Two yaml HTTP statuses (422 for `ERR_BATCH_SCOPE_MISMATCH`, `ERR_CLAIM_WINDOW_CLOSED`) contradict PRD §5's 409; tests defer to the registered status map, so the PRD wins.
- Field-name drift `confirmed_ivt_impressions` -> PRD-exact `ivt_impressions`.
- Noted but unasserted: the difficulty yaml's prose for `rejected_claim_over_exhausted_cap_...` states net 4760 where recomputation gives 4462.

No implementation existed under `workspace/` at Stage 2 exit, so the suite was statically validated and collected but never executed against a server.

**Orchestrator note on step sequencing (deviation, recorded for honesty):** the skill mandates launching Steps 5 and 6 concurrently in a single assistant message, which also gives Step 6 *physical* isolation from `test_suite/` (the directory does not exist when impl-gen starts). I issued Step 5 alone, so by the time Step 6 launched both test directories existed on disk. I compensated by making the prohibition explicit and absolute in the Step 6 prompt (no read/list/glob/grep of `test_helpers/`, `test_suite/`, or either `SCAFFOLD_*_DESIGN.yaml`), and Step 6 reported honouring it. Isolation was therefore contractual rather than physical for this run.

## Step 6: Generate implementation — 2026-09-04T00:52:00.000Z

The implementation is complete and verified.

## Location
`workspace/implementation/`

## Files and line counts (3,602 lines total)

| File | Bytes | Lines |
|---|---|---|
| `app.py` | 2898 | 90 |
| `calc.py` | 15158 | 430 |
| `db.py` | 4857 | 178 |
| `errors.py` | 9741 | 176 |
| `middleware.py` | 5537 | 181 |
| `response.py` | 1889 | 81 |
| `services.py` | 9224 | 236 |
| `validators.py` | 5177 | 144 |
| `requirements.txt` | 13 | 1 |
| `start.sh` (0755) | 398 | 10 |
| `routes/__init__.py` | 55 | 1 |
| `routes/helpers.py` | 1142 | 37 |
| `routes/core.py` | 16099 | 412 |
| `routes/lists.py` | 10583 | 283 |
| `routes/pages.py` | 27657 | 688 |
| `routes/measurement.py` | 14452 | 356 |
| `routes/claims.py` | 11991 | 298 |

All 17 files parse under `ast.parse`. `__pycache__` removed.

## Endpoint accounting
Route table dumped from the live `app.url_map`: **exactly 54 endpoints, none stubbed**, matching the PRD §4 table one-for-one (clock, advertisers, publishers + status + scorecard, campaigns, methodology-versions + audit-conclusion, pages + pre-bid-decision, page-classifications + review, appeals + evidence + decide, inventory-lists + entries + publish, pre-bid-segments + sync, measurement-batches + score + certify + ivt-findings, ivt-findings + confirm + retract, refund-claims + review/approve/reject/reverse).

## Design points honoured
- In-memory dicts only; store boots **empty** — a fresh-boot probe of `/campaigns`, `/measurement-batches`, `/inventory-lists` all returned `total_count: 0`. Nothing seeded, preloaded or hardcoded.
- Logical clock initialises to `2026-08-01T00:00:00Z` and only `POST /_clock/set_current_utc` advances it (confirmed in the fresh-boot `meta.api_request_timestamp`).
- `start.sh` pip-installs Flask only when missing, then `exec python3 app.py`, honouring `$PORT` — safe for `--isolation per-test-server` reboots without install contention across 8 concurrent rounds.
- `app.json.sort_keys = False` (Flask-3 correct form) preserves insertion-ordered JSON; 404/405/400/415/HTTPException/Exception all return the `{error_id, message}` envelope.

## Smoke verification (6 passes, port 18623, now shut down)
Positively exercised end to end: the 35-rung precedence ladder and both endpoint-local exceptions; all four synchronous cascades (methodology-DEFICIENT decertification through all four hops -> `BELOW_TARGET` -> `UNDER_REMEDIATION` -> segment `CAMPAIGN_UNDER_REMEDIATION`; quarantine-threshold and MFA-threshold publisher restriction -> list `RESTRICTED_PUBLISHER_ENTRY` -> segment `LIST_STALE`; appeal-overturn refund/remedy cascade with page -> `RECLASSIFIED` and the disputed record -> `VACATED`); the four pre-bid gates with their reason codes and `decisive_specificity` carrying its `entry_type`; the PRD's exact money worked example including per-cited-batch cent rounding (3503, not 3504); IVT max-per-family dedup with exact restoration on retraction; the double-entry ledger with full unwind on reversal; the lifetime credit cap; both OCC tokens; methodology lapse evaluation as the first step of scoring/certification/classification; pagination and conjunctive filters.

**Zero implementation changes were needed as a result of smoke testing.** Every apparent failure traced back to the agent's own test scenario, and each was resolved against the PRD text: SoD applies only to appeal decisions and audit conclusions (not classification review, §2.9/§3.4); rung 7 page-state precedes rung 19 appeal-pending (§3.4's "still at `MODEL_CLASSIFIED`" example); `BELOW_TARGET` -> `UNDER_REMEDIATION` is triggered only by cascade hop 3, never by certification (SCAFFOLD Campaign state machine); and a SUSPENDED methodology past `effective_to` correctly answers `ERR_METHODOLOGY_NOT_ACCREDITED` rather than `ERR_METHODOLOGY_LAPSED`, since §3.2 declares the lapse transition only from PROVISIONAL/ACCREDITED and calls SUSPENDED terminal.

Constraints observed throughout: `test_helpers/`, `test_suite/`, both `SCAFFOLD_*_DESIGN.yaml` files and all sibling task directories were never read, listed, globbed or grepped. Every smoke server was killed by the single PID resolved from `ss -ltnp | grep ':<port>'` — no pattern kill was ever issued. Ports 18623 and 18624 are both free.

## Step 7: Run tests and iterate — 2026-09-04T01:25:00.000Z

Clean 8-round sweep achieved. All fixes were in the test artifact; the implementation needed no changes.

## Summary

**Iterations run: 2** (sweep 1 -> diagnose/fix -> sweep 2 green).

Sweep 1: all 8 rounds `176/182` with the **identical** 6 failures — fully deterministic, no flakiness, no reaping signal. Sweep 2 (final, on disk at `workspace/implementation/results.{1..8}.json`): **182 passed / 0 failed / 0 errors / 0 skipped in every one of the 8 rounds.**

**Tests deleted: none.** All 6 failures were test-artifact bugs under STEP 2, or (for two) a STEP 1c partial-coverage split rather than a whole-test deletion.

**Fixes applied to `test_helpers/`**
- `test_helpers/assertions.py` — `assert_impression_conservation()`: the viewability-side identity (`measured == qualified + non_viewable + unmeasurable`) is now gated on `scored_at is not None`. PRD §2.11 scopes it to "For every **scored** batch", while PRD §3.7 says a freshly ingested batch stands "with every computed figure at its default and `scored_at` null" — so 0+0+0 vs 10000 on an `INGESTED` batch is PRD-correct, and the helper was over-applying the rule. The invalid-traffic identity (`net_billable + ivt == measured`) stays unconditional, matching PRD's "before a confirmation, after a confirmation, and again after the matching retraction". Fixed `test_13::test_ivt_family_maximum_dedups_overlapping_detectors_and_families_add`; no other call site was affected (all 16 others already pass scored/certified batches).

**Fixes applied to `test_suite/`**
- `test_suite/test_12_review_and_appeal_transitions.py` — 11 call sites had a double-unwrap, `get_success_data(validate_success(response, ...))`; both helpers return `body["data"]`, so the outer call got a `dict` and blew up with `AttributeError: 'dict' object has no attribute 'status_code'` before any assertion ran. Reduced to `validate_success(response, expected_status=...)`. This was the whole cause of the 3 test_12 failures (`test_override_review_replaces_categories_and_rescores_the_tier`, `test_mfa_restriction_lifts_only_after_reclassification_and_dependents_recover`, `test_claim_approval_and_rejection_forks_settle_only_their_own_batches`) — a pure harness-usage error; every assertion in those tests was preserved verbatim and all three pass with the full body now exercised.
- `test_suite/test_08_temporal_window_rules.py` — two assertions compared a **client-supplied** instant echoed back (`effective_from`, `window_start`) as a raw string, demanding `2026-06-01T00:00:00Z` where the server answered `2026-06-01T00:00:00.000Z`. STEP 1c split: PRD fixes the three-fractional-digit form only for the timestamps the server mints (§2.4 `created_at`, the envelope `api_request_timestamp`) and is silent on the textual form of a client-declared window echo, so both normalising and echoing verbatim are PRD-faithful readings. Kept the covered claim (the stored window *is* the declared instant) by comparing parsed instants via a local `_instant()` helper — the same tolerant approach `test_14` already uses. The suite was self-inconsistent here: it already asserts `.000Z` for the server-minted `scored_at`/`synced_at`.

**Fixes applied to `implementation/`: none.** No implementation defect surfaced; all mtimes are unchanged from before this session, and no assertion was weakened, skipped, or downgraded to reach green.

**Orchestrator independent verification (per the known "Step 7 claims a clean sweep with no artifacts" failure mode):** all 8 `results.{1..8}.json` exist on disk (~55 KB each, mtime 01:22) and every one parses to `passed=182 failed=0 total=182 errors=0 skipped=0`. Also grepped the whole test artifact for `pytest.mark.skip` / `pytest.mark.xfail` / `pytest.skip(` -> 0 hits, and confirmed 181 test functions still carry 181 `Design:` tags (unchanged from Step 5, consistent with "0 tests deleted").

## Step 8: Finalize PRD — 2026-09-04T01:35:00.000Z

`PRD_FINALIZED.md` written. Both real Step 7 candidates turned out to be genuine PRD under-determinations, and chasing the first one to its logical end surfaced two adjacent PRD claims that the implementation contradicts.

**Line counts:** PRD.md 481 lines / 108,998 bytes -> PRD_FINALIZED.md 481 lines / 111,292 bytes. 5 lines revised, 0 inserted, 0 deleted (+2.1% by bytes, 0% by lines).

**Changes**
- §2.4 — revise — pinned that the three-fractional-digit ISO 8601 UTC rendering is canonical for *every* instant the API emits, including client-supplied instants (`effective_from`, `effective_to`, `window_start`, `window_end`, `to_iso8601`), which are parsed to UTC and echoed normalised (`...T00:00:00Z` -> `...T00:00:00.000Z`) rather than kept as the caller's literal text — `db.py:92` (`fmt_dt`), `routes/measurement.py:114`, `routes/core.py:226`, `routes/core.py:35`.
- §3.7 — revise — replaced "every computed figure at its default" with the actual ingest defaults, notably `net_billable_impressions` = 0 (not `measured_impressions`) and `coverage_rate`/`viewability_rate`/`assessed_tier` null — `routes/measurement.py:114-135`.
- §2.11 — revise — scoped both conservation identities: the viewability identity is not in force on an `INGESTED` batch, and the IVT identity holds from the first confirmation, retraction or scoring onward (a batch that never had either is outside it, both figures still 0) — `routes/measurement.py:129`, `services.py:177-183`.
- §3.8 — revise — added that retraction *re-derives* `net_billable_impressions` as `measured_impressions` less the deduplicated total, so retracting the first-ever confirmation of a never-scored batch lands on `measured_impressions`, not on the 0 the batch carried at ingestion — `calc.py:306`, `services.py:182`.
- §2.10 — revise — pointed the "land exactly on their pre-confirmation values" claim at that §3.8 nuance — same code paths.

**Per-edit pre-edit search log**
1. §2.4 timestamp rendering. (a) Subject: textual form of every instant the API emits or stores. (b) Enumerated: `db.fmt_dt`/`now_iso`/`parse_dt` (db.py:74-109), `new_record`/`touch` (`created_at`, `updated_at`, db.py:130-168), `response._meta` `api_request_timestamp` (response.py:30), `current_utc` (core.py:35), `effective_from`/`effective_to` (core.py:226-227), `window_start`/`window_end` (measurement.py:114-115), `published_at` (lists.py:53,152), `synced_at` (lists.py:206,279), `scored_at` (measurement.py:134,202); grepped all `*_at`/date-like output keys and all `req_datetime` callsites — there are exactly five client-supplied instant inputs and no instant is ever emitted outside `fmt_dt`. (c) Adjustment: made the claim universal ("every instant the API ever emits") since no raw-echo path exists, and deliberately said nothing about sub-millisecond input handling (`fmt_dt` truncates) to avoid a claim Step 7 never probed.
2. §3.7 ingest defaults. (a) Subject: the value of each computed batch field before scoring, and who writes it. (b) Enumerated every writer of those fields by grep: ingestion dict (measurement.py:114-135), scoring (measurement.py:195-202), `services.recompute_batch_ivt` (179-183), `services.assess_batch_tier` (189-199); confirmed certification/quarantine/decertification never write them. (c) Adjustment: scoped the "only ever written by" clause to the *invalid-traffic* figures only — `assess_batch_tier` is also called from the appeal-overturn cascade (`routes/pages.py:586`), so an analogous claim about `assessed_tier` would have been a new mismatch.
3. §2.11 identity scoping. (a) Subject: when each conservation identity is true. (b) Enumerated: post-scoring algebra in `calc.viewability_and_coverage` (unmeasurable = measured-measurable, non_viewable = measurable-qualified -> identity structural), `calc.ivt_dedup` (net_billable = measured - capped ivt, cap guarantees non-negative), the three `recompute_batch_ivt` callsites (score / confirm / retract), and the `CERTIFIED`/`QUARANTINED`/`DECERTIFIED` paths which leave the figures alone. (c) Adjustment: phrased the IVT exception as "never scored and never had a finding confirmed or retracted" rather than "on an `INGESTED` batch" — an `INGESTED` batch that has had a confirm/retract *does* satisfy the identity, so the narrower phrasing would have been wrong.
4. §3.8 retraction restoration. (a) Subject: values of the IVT figures after a retraction leaves no confirmed finding. (b) Enumerated: `calc.ivt_dedup` (calc.py:283-307) — empty confirmed set gives ivt 0, `net_billable = measured`; `services.recompute_batch_ivt` as the only caller-facing writer; retract route (measurement.py:355) and confirm route (333). (c) Adjustment: framed it as a re-derivation and named the *only* divergent case (first-ever confirmation on an unscored batch) rather than weakening the general "no residual drift" guarantee, which does hold everywhere else.
5. §2.10 cross-reference. (a) Subject: same as (4) — the cascade-level restatement of the restoration guarantee. (b) Enumerated: grepped every PRD occurrence of `net_billable`/"pre-confirmation"/"residual drift" (lines 178, 286, 300, 316, 318) against the same `ivt_dedup`/`recompute_batch_ivt` paths. (c) Adjustment: used a pointer to §3.8 instead of restating the nuance, to keep the §2.10 sentence about backward-cascade policy intact.

## Step 9: Complete PRD — 2026-09-04T02:05:00.000Z

Run as THREE sequential file-partitioned passes over the 3,602-line implementation, because a single-shot Step 9 subagent routinely returns a PRD_COMPLETED.md byte-identical to its input (i.e. the scan never actually ran). Partition: Pass A = app.py / db.py / response.py / middleware.py / errors.py / validators.py / routes/helpers.py / routes/core.py; Pass B = calc.py / services.py / routes/pages.py; Pass C = routes/lists.py / routes/measurement.py / routes/claims.py. Pass A created PRD_COMPLETED.md from PRD_FINALIZED.md; B and C edited it in place, additively, each receiving a handover note listing the prior passes' pins so they would not duplicate them.

**Totals: 59 edits — 56 ambiguity-pins, 3 mismatch-revisions.** PRD_FINALIZED.md 481 lines / 111,292 chars -> PRD_COMPLETED.md 481 lines / 123,588 chars (+12,296 chars, +11.0%; 51 lines revised, 0 lines added — every edit in-paragraph, no new sections).

### Pass A (18 edits: 17 ambiguity, 1 mismatch) — 115,394 chars
- §2.1 — insert — ambiguity — headers whitespace-trimmed so a blank header counts as absent; on the clock endpoint an absent/unknown role is 401, a recognised non-`PlatformAdmin` role is `ERR_UNAUTHORIZED_ROLE`, `X-User-ID` not required — middleware.py:54, 81-89
- §2.2 — insert — ambiguity — `api_request_id` is `req_` plus exactly 20 uppercase-alphanumeric chars — response.py:10-24
- §2.3 — insert — ambiguity — out-of-range/non-integer `limit`/`offset` rejected with `ERR_INVALID_REQUEST` (422), not clamped; blank means default — middleware.py:131-161
- §2.3 — insert — ambiguity — `created_at` ties broken by creation sequence — db.py:173-178
- §2.3 — insert — ambiguity — blank filter params ignored; filters match by exact string equality — routes/helpers.py:23-37, middleware.py:164-169
- §2.4 — insert — ambiguity — a submitted instant with no zone designator is read as already UTC — db.py:86-89
- §2.4 — insert — ambiguity — clock setter accepts any instant, no monotonicity check, answers an object carrying `current_utc` alone — routes/core.py:29-35
- §2.8 p5 — insert — ambiguity — a required scalar identifier field that is absent/null/non-string is unresolvable at priority 5 and yields the 404, not `ERR_INVALID_REQUEST` — routes/core.py:365-368 (same pattern lists.py:35, measurement.py:58-63, claims.py:40-45, pages.py:262)
- §2.8 p6 — insert — ambiguity — JSON `null` counts as absent; unparseable/non-object body fails here; absent body read as `{}` — validators.py:17-19, middleware.py:120-128, app.py:48-58
- §2.9 — insert — ambiguity — both SoD comparisons fire only when caller id and stored id are both non-null — routes/core.py:287-288, routes/pages.py:630
- §2.10 — insert — ambiguity — `version` increments exactly once per record per request regardless of hop count; a record created in the request stays at 1 — db.py:131-170
- §3.1 — insert — ambiguity — `primary_domain` validated only as a 1-300-char non-blank string, stored verbatim; duplicate test is exact string equality — routes/core.py:75-81
- §3.1 — **revise** — **mismatch** — campaign list filters are `advertiser_id` and `status` only (PRD claimed `coverage_status` and `format` too); an `Advertiser` is always narrowed to its own campaigns — routes/core.py:409-412
- §3.1 — insert — ambiguity — supplied `reason` on a standing change accepted but never persisted; `status_reason` always holds the platform code — routes/core.py:122, 135/138
- §3.1 — insert — ambiguity — explicit `new_status` of `RESTRICTED` answers `ERR_INVALID_PUBLISHER_STATE`, except `ERR_PUBLISHER_DELISTED` returns first — routes/core.py:124-141
- §3.2 — insert — ambiguity — `effective_to <= effective_from` answers `ERR_INVALID_REQUEST`; duplicate `version_code` tested before window overlap so it wins when both apply — routes/core.py:195-221
- §3.2 — insert — ambiguity — `PASSED` reachable only from `PROVISIONAL`; a `deficiency_note` on a `PASSED` outcome is ignored — routes/core.py:282-298
- §4 — insert — ambiguity — trailing slash optional on every path — app.py:20
- §5 — insert — ambiguity — `ERR_NOT_FOUND` (404) for unmatched routes and `ERR_METHOD_NOT_ALLOWED` (405) for unsupported methods, both absent from the catalogue table — app.py:36-46

### Pass B (20 edits: 18 ambiguity, 2 mismatch) — 119,545 chars
- §2.1 — revise — mismatch — publisher ownership on classification reads/lists applies to the page behind *any* classification record and any appeal, not only "an appealed classification" — routes/pages.py:346,363-367,510,528
- §2.6 — insert — ambiguity — rounded rates/scores emitted as JSON numbers, so trailing zeros are not preserved (0.7000 -> `0.7`, 70.00 -> `70.0`); rounding rules govern the stored value — calc.py:150-167
- §2.7 — insert — ambiguity — `expected_page_version`/`expected_campaign_version` are required non-negative integers; absent/null/non-integer/negative fails priority 6 rather than reaching the 412 — routes/pages.py:270, routes/claims.py:56
- §3.2 hop 3 — insert — ambiguity — a campaign already in `UNDER_REMEDIATION` is never lifted by decertification's coverage recomputation; only certification can — services.py:157-163 vs 150-154
- §3.3 — insert — ambiguity — page-URL duplicate test is exact string equality; page registration ignores publisher standing — routes/pages.py:72-74
- §3.3 — insert — ambiguity — `domain` is the lowercase host alone, userinfo and port stripped, empty string when the URL has no host — routes/pages.py:54-56
- §3.3 — insert — ambiguity — `mfa_flag` filter parsing (`true|1|yes` / `false|0|no`, case-insensitive; any other non-empty value matches nothing rather than erroring); `Publisher` callers see only their own pages — routes/pages.py:113-118, middleware.py:172-181
- §3.3 — insert — ambiguity — client-supplied `APPEAL_REMEDY` answers `ERR_INVALID_REQUEST`; the two body references resolve page-before-methodology — routes/pages.py:262-269
- §3.3 — **revise** — **mismatch** — an already-`LAPSED` (or just-lapsed) methodology version on classification creation answers `ERR_METHODOLOGY_LAPSED`, not `ERR_METHODOLOGY_NOT_ACCREDITED`, which is reserved for `SUSPENDED` — services.py:53-60, routes/pages.py:295
- §3.3 — insert — ambiguity — `category_codes` optional, defaults to `[]`, may repeat a code — routes/pages.py:271-278, validators.py:124
- §3.3 — insert — ambiguity — `base_risk_points` counts every occurrence, so a repeated code contributes its weight twice — calc.py:207-211
- §3.3 — insert — ambiguity — `classifier_kind` does not affect the page transition: a `HUMAN` write also lands the page at `MODEL_CLASSIFIED` awaiting review — routes/pages.py:335
- §3.3 — insert — ambiguity — `Publisher` callers see only classifications of their own pages; a cross-publisher single read answers `ERR_NOT_RESOURCE_OWNER` — routes/pages.py:346,363-367
- §3.4 — insert — ambiguity — `OVERRIDE`'s `revised_category_codes` requirement answers `ERR_INVALID_REQUEST` and, being conditional, is checked *after* the state guard; an empty array is a legitimate clearing revision — routes/pages.py:390-407
- §3.4 — insert — ambiguity — a `revised_category_codes` array supplied with `CONFIRM` is still shape-checked, then ignored — routes/pages.py:379-386,398-399
- §3.4 — insert — ambiguity — the 14-day appeal filing boundary is inclusive — routes/pages.py:483
- §3.4 — insert — ambiguity — `Publisher` callers see only appeals against their own pages — routes/pages.py:527-528
- §3.4 — insert — ambiguity — `revised_tier` drawn from the five graded tiers; `UNRATED` answers `ERR_INVALID_REQUEST` — routes/pages.py:621, calc.py:22
- §3.4 — insert — ambiguity — `MORE_EVIDENCE` leaves `decided_by_user_id` null and accepts-but-ignores `revised_tier`; an evidence round leaves the previous `decision_note` in place — routes/pages.py:546-549,627,652-656
- §3.4 — insert — ambiguity — the remedy record copies the disputed record's evidence and risk arithmetic verbatim (`base_risk_points`/`adjusted_risk_points` not re-derived) and stamps both `classifier_user_id` and `reviewed_by_user_id` with the officer, `review_note` null — routes/pages.py:553-577
- §3.6 — insert — ambiguity — pre-bid entry tie at equal `specificity_rank`, action and `created_at` broken by append order — routes/pages.py:173-179, db.py:173-178

### Pass C (21 edits: 21 ambiguity, 2 mismatch — two edits carry two pins each) — 123,588 chars
- §2.1 — insert — ambiguity — extended both ownership enumerations: advertiser side gains a measurement batch's campaign's `advertiser_id`; publisher side gains the batch behind any IVT finding and a refund claim's own `publisher_id` — measurement.py:43-47,259-262, claims.py:28-32
- §2.5 — insert — ambiguity — `UNRATED` is never an accepted *input* value on a client-supplied tier field — lists.py:182, core.py:371, pages.py:621
- §2.8 (final para) — **revise** — **mismatch** — the ingestion `ERR_METHODOLOGY_FAMILY_MISMATCH` guard was described as "evaluated together with that endpoint's other referential checks"; impl runs it after the priority-6 shape checks and before priority 21 — measurement.py:69-79
- §3.5 — insert — ambiguity — list `name` is 1-120 non-blank; collision is exact string equality, reached only after the payload's priority-6 checks — lists.py:36-44
- §3.5 — insert — ambiguity — an `Advertiser` caller sees only its own lists whether or not it supplies `advertiser_id` — lists.py:78-79
- §3.5 — insert — ambiguity — `entry_value` is 1-300 non-blank characters — lists.py:93
- §3.6 — insert — ambiguity — an optional list id omitted/JSON `null` = not pinned; a non-string value is unresolvable at priority 5 -> `ERR_INVENTORY_LIST_NOT_FOUND` — lists.py:170-181
- §3.6 — insert — ambiguity — an `Advertiser` caller sees only segments of its own campaigns — lists.py:241-247
- §3.6 — insert — ambiguity — sync evaluates the pinned-list publication guard before the campaign-standing guard, so both failing yields `ERR_LIST_NOT_PUBLISHED` — lists.py:268-272
- §3.7 — insert — ambiguity — the four ingestion body references resolve in payload order: campaign, publisher, page, methodology version — measurement.py:57-67
- §3.7 — insert — ambiguity — `Publisher` sees only its own batches, `Advertiser` only its own campaigns' batches — measurement.py:165-173
- §3.8 — insert — ambiguity — `flagged_impressions` of 0 or below fails at priority 6 with `ERR_INVALID_REQUEST` (not the IVT error) — measurement.py:273
- §3.8 — insert — ambiguity — recording a finding is available whatever the batch's `scoring_status`; only confirm/retract demand an unadjudicated batch — measurement.py:265-292
- §3.8 — insert — ambiguity — confirm order pinned: state (7) -> confidence floor -> adjudication guard — measurement.py:322-330
- §3.8 — insert — ambiguity — `retract_reason` is 1 to 500 non-blank characters — measurement.py:342
- §3.9 — insert — ambiguity — priority-5 element existence reaches only *string* elements of `batch_ids`; non-array/non-string/count/distinctness all fall to priority 6 — claims.py:47-55
- §3.9 — insert — ambiguity — `batch_ids` stored and echoed in the client's supplied order, while recomputations walk cited batches by ascending `created_at` — claims.py:87, services.py:205-207
- §3.9 — insert — ambiguity — the 30-day claim window boundary is inclusive — claims.py:79-82
- §3.9 — insert — ambiguity — the cited-batch filter accepts `batch_ids` or the alias `batch_id` (singular wins), matching by membership; plus Publisher/Advertiser list scoping — claims.py:133-144
- §3.9 — insert — ambiguity — the `ERR_APPEAL_PENDING` review precondition is evaluated only after the state guard — claims.py:171-176
- §3.9 — **revise** — **mismatch** — the non-zero-credit guard was glossed as equivalent to "`net_credit_cents` not greater than zero"; impl tests `credited_impressions` alone, so a positive basis whose per-batch pricing rounds to 0 cents (e.g. `cpm_cents` 1 over 400 impressions) is approved with a 0-cent posting — claims.py:207, calc.py:360-362
- §3.9 — insert — ambiguity — `reversal_reason` is 1 to 500 non-blank characters — claims.py:271

### Handover items judged and deliberately left alone
- `calc.batch_is_defective` coverage-floor limb: unreachable for claimable batches (`QUARANTINED`/`DECERTIFIED` both require prior scoring, so `coverage_rate` is non-null and the methodology always resolves).
- `services.compute_basis` treating a missing campaign as `cpm_cents` 0: unreachable — `campaign_id` is a resolved priority-5 reference at claim creation and no delete endpoint exists.
- `ERR_VALIDATION` (400): defined in errors.py but never raised anywhere and absent from §5; left as-is by all three passes.

### Closing sanity check (Pass C) — PASS
All sections present and in order (§1; §2.1-2.11; §3.1-3.9; §4; §5). §4 has exactly 54 endpoint rows, §5 exactly 67 error rows. Spot-checked 27 distinctive Pass A/B phrases — all still present exactly once, nothing clobbered. File ends at a real boundary (final `ERR_CREDIT_CAP_EXCEEDED` row of the §5 table, trailing newline), not mid-sentence.

**Orchestrator independent verification (per the known "Step 9 never ran" failure mode):** `cmp -s PRD_FINALIZED.md PRD_COMPLETED.md` -> DIFFERS (not byte-identical); `diff` reports 102 changed lines (51 revised pairs); 481 lines / 123,588 chars; 28 headings intact; 67 `ERR_` rows; tail ends on the completed §5 table. No implementation or test file was touched by Step 9, so the Step 7 green sweep still stands.

## Pipeline complete — 2026-09-04T02:06:00.000Z

Steps 1-9 all executed. Final state: 182/182 tests passing in all 8 parallel sweep rounds; PRD.md -> PRD_FINALIZED.md (5 revisions) -> PRD_COMPLETED.md (59 further edits). One recorded process deviation: Steps 5 and 6 were launched sequentially rather than in a single message, so Step 6's isolation from `test_suite/` was contractual (explicit prohibition, honoured per its report) rather than physical.
