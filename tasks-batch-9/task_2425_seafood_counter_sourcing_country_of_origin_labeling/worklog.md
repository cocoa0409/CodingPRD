# Worklog — task_2425_seafood_counter_sourcing_country_of_origin_labeling

## Step 1: Create task directory — 2026-09-02T16:01:12.155Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2425_seafood_counter_sourcing_country_of_origin_labeling` and its `workspace/` subdirectory. Index 2425 was pre-assigned by the orchestrating pipeline (no ./tasks/ scan performed, per instruction — concurrent pipelines on this host).

## Step 2: Generate scaffold artifacts — 2026-09-02T17:40Z

Wrote `SCAFFOLD.yaml` (§1.0–§1.7), `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (§1.8, 22 instances across all 9 rule ids) and `SCAFFOLD_CORNER_DESIGN.yaml` (§1.9, 52 instances across the 9 claim-extraction sections: 38 with test recipes, 14 `excluded_because` stubs pointing at the §1.8 instance that already covers the corner). Generated only from the scenario line plus the scaffold-generator skill and its claim-extraction guide; no sibling task under `tasks/` was inspected. `scaffold_lint.py` reports `VERDICT: clean lint` (62 endpoints, 13 entities, 680 calls scanned).

### Step 2 subagent summary (verbatim, orchestrator record)

All three scaffold artifacts are complete and the mandated lint passes on the first run.

Lint verdict block, verbatim from `python3 /home/ubuntu/github/CodingPRD/skills/prd-bench-scaffold-generator/scaffold_lint.py tasks/task_2425_seafood_counter_sourcing_country_of_origin_labeling/`:

```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           tasks/task_2425_seafood_counter_sourcing_country_of_origin_labeling/SCAFFOLD.yaml
  Difficulty design:  tasks/task_2425_seafood_counter_sourcing_country_of_origin_labeling/SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      tasks/task_2425_seafood_counter_sourcing_country_of_origin_labeling/SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    62
  §1.1 entities declared:     13
  §1.8 instances scanned:     22
  §1.9 instances scanned:     38
  Calls scanned (§1.8+§1.9):  680

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```
(exit code 0)

Files, all under `/home/ubuntu/github/CodingPRD/tasks/task_2425_seafood_counter_sourcing_country_of_origin_labeling/`:
- `SCAFFOLD.yaml` — §1.0–§1.7 only (no `scaffold_difficulty_design` / `scaffold_corner_design` keys present; verified).
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single top-level key `scaffold_difficulty_design`.
- `SCAFFOLD_CORNER_DESIGN.yaml` — single top-level key `scaffold_corner_design`.
- `worklog.md` — appended a Step 2 entry to the pipeline's existing worklog.

Scaffold contents (`domain_name: seafood-counter-cool-ops`, `api_prefix: /seafood-ops`):
- 13 entities: Counter, Supplier, Species (immutable), SupplierLot, CaseLabel, AdvertisedItem, IceBedReading (immutable), ColdChainExcursion, VerificationSample, SimpDocument, SustainabilityCertification, ShrinkEvent, ComplianceViolation.
- 14 state machines / dimensions, including SupplierLot's three parallel dimensions (intake / label / chargeback) and AdvertisedItem's fork-join (status + cool_review + claim_review).
- 8 calculations: COOL label-content derivation, shrink valuation (dual variant), cook-and-sell conversion recovery, supplier chargeback assessment (pinned 5-step tiered), substitution risk index (dual variant, decay), verification sampling plan, cold-chain exposure replay, counter posture derivation.
- 55 ordered validations (auth 401/403 → scope → segregation of duties → 13 existence 404s → shape 400 → 2 OCC 412s → 11 state 409s → posture/safety 409s → business 422s → fiscal 402/422), 55 error codes, 62 endpoints, 5 roles (segregation-of-duties model, two entity-backed), 2 OCC concurrency rules.

Design files:
- §1.8: 22 instances across all 9 difficulty rules (dual_variant_calc 2, combinatorial_formula 3, non_linear_state_machine 3, transitive_cascade 2, priority_pair_validation_conflict 2, boundary_precision_check 3, cross_entity_state_dependency 3, resource_temporal_overlap 2, compensating_invariant 2).
- §1.9: 52 instances across all 9 claim-extraction sections — 38 with full test recipes, 14 `excluded_because` stubs (no recipes) pointing at the §1.8 instance that already covers the corner; per section: entities 11, state_machines 9, calculations 8, validations 11, endpoints 3, errors 1, rbac 4, cross_cutting_complexity_layers 4, consistency_model 1. All 74 instance names are unique across both design files, and every stub's `difficulty_instance` reference resolves to the correct rule id.

Checks beyond the lint: both design files parse with exactly one top-level key; every instance has either a `test_recipe` or an `excluded_because` (never both); no forbidden concurrency vocabulary in any file; every asserted money/weight literal recomputed from the declared formulas (e.g. the cold-chain disposal shrink 18650 at factor 2.0, the 10950 unsold-fresh shrink, chargebacks 47840 / 149000, 60-vs-61-minute severity boundary, 2-sample verification plan). No sibling task directory was read, listed, or grepped at any point.

## Step 3: Copy shared files — 2026-09-02T17:41:00.000Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` to `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-02T17:53:00.000Z

Orchestrator anti-truncation verification (independent of the subagent's own): `wc -l workspace/PRD.md` = 448; `tail -25` ends on the complete table row `| \`ERR_SUPPLIER_CREDIT_HOLD\` | 402 Payment Required |`; `grep '^#'` confirms §1–§5 with all 11 §2 and 9 §3 subsections plus §4 endpoint table and §5 error catalogue present. Ends at a real section boundary — no regeneration needed.

### Step 4 subagent summary (verbatim)

PRD generated at `/home/ubuntu/github/CodingPRD/tasks/task_2425_seafood_counter_sourcing_country_of_origin_labeling/workspace/PRD.md`.

**Structure** — 11 §2 subsections (domain-derived: posture gating, rounding discipline, stale-version rejection, order of rejection, cascade discipline, ledger identities), 9 §3 subsections organised as a chronological lifecycle (configuration → receipt → documentation → casing → labelling → certification → advertising → cold chain → verification/recovery → shrink/remediation), 4-column §4 table, 2-column §5 table.

**Hard Contracts (all PASS)**

```
Field coverage check:
- entities[].fields: 144 required, 144 present, 0 missing
- endpoints[].request_body: 65 required, 65 present, 0 missing
- endpoints[].query_params: 20 required, 20 present, 0 missing
- endpoints[].path_params: 13 required, 13 present, 0 missing
Status: PASS
```

```
Rule coverage check:
- validations[] with priority: 55 checked, 55 expressed in prose (ordered list in §2.9), 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (write_endpoint + expected_lot_version / expected_counter_version + ERR_STALE_LOT_VERSION / ERR_STALE_COUNTER_VERSION + 412), 0 missing
- state_machines[].transitions: 58 checked across 14 machines, 58 fully expressed, 0 missing
- calculations[]: 8 checked, 8 fully expressed (all constants embedded in business context; pinned rounding/evaluation orders stated), 0 missing
- validations[] conditions: 55 checked, 55 matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: 37 checked, 37 expressed, 0 missing
- entities[].fields[] structured content: 144 checked, 144 reconstructible from prose, 0 missing
- sibling-branch symmetry: 6 groups checked (cool vs. claim review branches; RELEASE vs. DISPOSE disposition; convert-path vs. VALUED-direct posting; ROLLING_CYCLE vs. LIFETIME risk variants; label-withdrawal vs. ad-retraction under certificate enforcement; the five CaseLabel withdraw reasons), 6 with equal prose density, 0 asymmetric
Status: PASS
```

```
Path purity check (§3 only):
- backtick tokens scanned: 924
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

**Other verifications** — §2.2 matches `section-2.2-response-structure.md` byte-for-byte (substring match confirmed). All 62 scaffold endpoints present as 62 table rows; all 55 error IDs present as 55 table rows. No fuzzy/approximating words ("approximately", "roughly", "conservatively", etc.) anywhere in the file. All 5 role names, every state enumeration value, and every enum-typed field value appear verbatim.

**Anti-truncation check** — file is 449 lines and ends cleanly at a real section boundary: the last line is the final complete row of the §5 table, `| `ERR_SUPPLIER_CREDIT_HOLD` | 402 Payment Required |`, followed by a trailing newline. Every section my outline promised (§1–§5, all 11 §2 and 9 §3 subsections) is present. No regeneration was needed.

Note: I did not open `SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`, or `worklog.md`.

## Step 5: Generate unit tests — 2026-09-02T20:25:00.000Z

Launched concurrently with Step 6 in a single assistant message (physical isolation: `test_suite/` did not exist when the impl-gen subagent started, so it could not read tests; the impl-gen prompt also forbade reading `test_helpers/`).

### Step 5 subagent summary (verbatim)

All gates are green. Final state of the deliverable.

## Files written

`test_helpers/` (Stage 1, 9 files): `__init__.py`, `api_client.py`, `api_errors.py`, `assertions.py`, `constants.py`, `factories.py`, `fixtures.py`, `test_users.py`, `types.py`
— all under `/home/ubuntu/github/CodingPRD/tasks/task_2425_seafood_counter_sourcing_country_of_origin_labeling/test_helpers/`

`test_suite/` (Stage 2, `conftest.py` + 16 test modules) under `/home/ubuntu/github/CodingPRD/tasks/task_2425_seafood_counter_sourcing_country_of_origin_labeling/test_suite/`:

Queue A (depth, `SCAFFOLD_DIFFICULTY_DESIGN.yaml`) — 8 files, 49 tests
- `test_01_shrink_valuation_and_cook_recovery.py` (8)
- `test_02_supplier_chargeback_and_ledger.py` (8)
- `test_03_verification_sampling_and_supplier_standing.py` (6)
- `test_04_cascade_chains.py` (6)
- `test_05_cold_chain_boundaries.py` (5)
- `test_06_case_label_certification_and_import_documents.py` (5)
- `test_07_advertising_review_fork.py` (5)
- `test_08_occupancy_interval_conventions.py` (6)

Queue B (breadth, `SCAFFOLD_CORNER_DESIGN.yaml`) — 8 files, 53 tests
- `test_09_entity_defaults_and_projections.py` (12)
- `test_10_state_machine_edges.py` (11)
- `test_11_calculation_input_sets_and_bands.py` (3)
- `test_12_receipt_relabel_and_claim_validations.py` (6)
- `test_13_weight_conversion_and_fiscal_validations.py` (8)
- `test_14_ad_action_endpoints_and_error_envelope.py` (3)
- `test_15_role_scopes_and_shared_operations.py` (5)
- `test_16_posture_escalation_occ_and_remediation.py` (5)

## Counts

- 102 tests total: queue A 49, queue B 53.
- 60 distinct design instances covered: all 22 non-stub difficulty instances (≥2 tests each) and all 38 non-stub corner instances (≥1 test each).
- The 14 corner instances carrying `excluded_because:` are stubs and were deliberately not translated.

## Instances skipped

None. Every non-stub instance in both indices passed the PRD-first two-condition filter and was translated. Two individual assertions inside otherwise-derivable instances were omitted because the PRD does not derive them (the instance itself is still covered):

1. `Corner/validations/relabel_guards_species_then_market_name_then_accepts` — the yaml asserts `CaseLabel.withdraw_reason == "MISMATCH"`, which is not a member of the PRD's `withdraw_reason` enum (`SPECIES_MISMATCH` / `MANUAL` / …). Assertion dropped; the species guard, market-name guard and the accepted relabel are all asserted.
2. `Corner/validations/weight_ceilings_on_sales_and_shrink_are_enforced_against_remaining` — the yaml asserts a shrink posting that zeroes the lot yields `intake_status == DEPLETED`, `case_slot == null` and a `WITHDRAWN`/`MANUAL` label. PRD §3.3 grants `DEPLETED` only "When a sale brings `remaining_weight_kg` to exactly 0.000", and §3.9 posting only moves a lot to `DISPOSED` for a full-weight `MISLABEL_DESTRUCTION`. Those three assertions dropped; `POSTED`, `remaining_weight_kg == 0.000` and the counter ledger 10950/10950/0 are asserted.

## Verification

- Citation audit (`/tmp/audit_citations.py`): `files: 16  tests: 102`, `queue A (Difficulty): 49  queue B (Corner): 53`, `distinct instances covered: 60`, `all citation checks passed` — every docstring carries exactly one verbatim `PRD §x: "…"` quote that grep-matches `PRD.md`, and exactly one trailing `Design:` tag resolving to a real non-stub instance name; no skip/xfail markers and no scaffold references anywhere.
- Corner coverage cross-check: the tag set equals the 38 non-stub names exactly (`missing: []`, `tagged but stub/unknown: []`).
- `pytest test_suite --collect-only -q` → 102 collected, 0 errors.
- `pyflakes test_suite/*.py test_helpers/*.py` → clean.
- `workspace/implementation/` and `worklog.md` were never read; no tests were executed against an implementation.

## Step 6: Generate implementation — 2026-09-02T20:25:30.000Z

### Step 6 subagent summary (verbatim)

The implementation is complete.

**Location:** `/home/ubuntu/github/CodingPRD/tasks/task_2425_seafood_counter_sourcing_country_of_origin_labeling/workspace/implementation/`

**Files written (20, ~3,500 lines of Python):**
- `start.sh` — bash launcher, `cd` to its own directory, installs Flask only if missing, `exec python3 app.py`; honours `PORT` (default 10000), binds 0.0.0.0
- `requirements.txt` — `Flask>=2.2`
- `app.py` — imports `web` plus the seven route modules, `app.run(threaded=True, use_reloader=False)`
- Infrastructure: `store.py` (13 in-memory dicts + logical clock + RLock), `errors.py` (all 57 error ids → status map), `common.py` (ROUND_HALF_UP decimal helpers, `base_record`, `touch`), `envelope.py` (meta/`response_type`/`data`, pagination), `validators.py` (typed body validation, FK sentinel for wrong-typed ids), `auth.py` (role + `X-User-ID` scoping), `calc.py` (all 8 pinned calculations), `serializers.py` (13 entity serializers), `services.py` (derived posture, supplier risk indices, both cascades), `web.py` (route decorator, transaction/versioning wrapper, generic `listing()`)
- Routes: `routes_core.py` (9: clock, counters, suppliers, species), `routes_lots.py` (9), `routes_labels_ads.py` (12), `routes_cold.py` (6), `routes_samples.py` (6), `routes_docs.py` (10: SIMP + certifications), `routes_shrink.py` (11: shrink valuation/conversion + violations)

**Endpoint count: 62** — exact match to the PRD §4 table, proven by parsing the table's 62 rows and diffing against Flask's `url_map` (`missing: []`, only extra is Flask's built-in `/static/<path:filename>`).

**Storage:** in-memory dicts keyed by id only. No SQLite, no JSON dump, no `/tmp` cache — grep confirms no `open(`/`json.dump`/`sqlite` anywhere. Nothing is seeded: a fresh process starts with every collection empty and the logical clock at `2026-08-01T00:00:00Z` (never falls back to wall clock, so `api_request_timestamp` is deterministic too).

**Fresh-boot verification (just re-run):** `PORT=14312 bash start.sh` from a clean process → `POST /seafood-ops/counters` returned **201** with `version: 1`, `posture: OPEN`, timestamps `2026-08-01T00:00:00.000Z`; `GET /seafood-ops/counters` returned **200** with `total_count: 1` (confirming the store was empty at boot). Server then killed; no stray `app.py` processes remain (three leftovers from earlier sessions were also cleaned up).

**Behavioural verification:** three throwaway scripts under `/tmp` exercise happy paths (50/50 OK across every module), negatives (401 missing/unknown role, 403 role + scope, 404-before-400 ordering, 405, pagination and body validation, error envelope carries only the two meta keys), and edges (412 OCC on both `expected_lot_version` and `expected_counter_version`, SUPERSEDED label chain, half-open ad window overlap, 4.4 °C compliant vs 4.5 °C breach, replay to CRITICAL at 240 min, RELEASE refused for CRITICAL, DISPOSE cascade with a COLD_CHAIN_DISPOSAL shrink event, 30-minute sanitation buffer, SIMP deficient→amend→accept cure dropping 5→3 points, certificate expiry/sweep-too-early, cool REJECT → ad REJECTED, retest loop bounded at 2, SUSPENDED gating at 13 points). Ledger and index spot-checks matched hand calculations.

Lint is clean apart from the intentional `noqa`'d route-module imports in `app.py` and two harmless re-exports (`ApiError` in `envelope.py`, `fail` in `web.py`).

## Step 7: Run tests and iterate — 2026-09-02T19:45:00.000Z

**Orchestrator independent verification (decision recorded per AUTONOMY).** The Step 7 subagent reported a clean confirmation sweep, but on exit `workspace/implementation/results.*.json` and `workspace/sweep.log` did not exist — the subagent's own sweep artifacts were absent, so its clean-sweep claim was unverifiable from disk. Its code edits *had* landed (`test_helpers/assertions.py` 19:20 with `assert_instant`, `test_helpers/factories.py` 19:18, `assert_instant` referenced across 8 test modules). Rather than accept the claim, I re-ran the full 8-round parallel sweep myself, wrapped in `setsid nohup` exactly as the pipeline instruction prescribes.

Verified result of the orchestrator-run sweep (~185 s per round):

```
results.1.json 102 / 102 failed= 0 errors= 0
results.2.json 102 / 102 failed= 0 errors= 0
results.3.json 102 / 102 failed= 0 errors= 0
results.4.json 102 / 102 failed= 0 errors= 0
results.5.json 102 / 102 failed= 0 errors= 0
results.6.json 102 / 102 failed= 0 errors= 0
results.7.json 102 / 102 failed= 0 errors= 0
results.8.json 102 / 102 failed= 0 errors= 0
ALL8_GREEN
```

`grep -c 'Terminated' workspace/sweep.log` = 0, so no round was reaped; every round reached its own natural completion. Step 7 is therefore genuinely green on all 8 concurrent rounds, and the required `results.{1..8}.json` artifacts now exist on disk.

### Step 7 subagent summary (verbatim)

All done — clean 8-round parallel sweep, 102/102 in every round.

## Summary

**Iterations run:** 4 sweeps (3 diagnostic + 1 confirmation).
- Sweep 1: 74/102 in all 8 rounds, 28 unique failures (fully deterministic — no flakiness).
- Sweep 2: 101/102 in all 8 rounds, 1 failure.
- Sweep 3: 102/102 in 7 rounds; 1 round lost `test_03_a_subtotal_of_exactly_fifty_thousand_cents_earns_the_eight_percent_rate` to `ConnectionResetError` (load artifact — no `Terminated` in the sweep log, endpoint has no timing logic).
- Sweep 4 (confirmation): **102/102 in all 8 rounds**, ~197 s per round.

**Tests deleted:** none. Every failing assertion traced to a PRD sentence; all 28 were test-artifact bugs.

**Fixes applied to `test_helpers/`:**
- `test_helpers/factories.py` — `tilapia_lot_payload` / `snapper_lot_payload`: built the variant dict and merged `**overrides` into it before delegating to `lot_payload`, instead of passing variant defaults as keyword args alongside `**overrides`. The old form raised `TypeError: lot_payload() got multiple values for keyword argument 'lot_code'` (and `'received_weight_kg'`) for every test that overrode a variant field — 8 of the 28 failures.
- `test_helpers/assertions.py` — added `assert_instant(actual, expected)`, which validates the value is an ISO 8601 UTC timestamp and then compares parsed instants. PRD §2.4 pins three fractional digits for `created_at`; it does not pin a per-field digit count for the logical-clock-stamped fields or for client-supplied instants a record copies (`ad_start_at`, excursion `started_at`/`ended_at`). 13 failures were bare-`Z` string equality (`'…T08:00:00.000Z' == '…T08:00:00Z'`) against a correctly 3-digit-rendering implementation.

**Fixes applied to `test_suite/`** (assertion/setup faithfulness, not weakening):
- 21 timestamp equality sites across `test_04`, `test_05`, `test_06`, `test_08`, `test_09`, `test_10`, `test_11`, `test_16` switched from exact-string `==` to `assert_instant`.
- `test_13_weight_conversion_and_fiscal_validations.py` — `_assessed_chargeback_of_forty_seven_thousand_eight_hundred_forty` and `_supplier_holding_a_hundred_and_forty_nine_thousand_outstanding`: added the missing `fixtures.publish_case_label(...)` before the mismatch result. PRD §3.8/§2.10 route the chargeback through *"every `PUBLISHED` case label for the lot is withdrawn … that withdrawal creates the `MISLABEL_DESTRUCTION` shrink event, and the shrink event's creation drives the lot's `chargeback_status` from `NONE` to `ASSESSED`"* — with no published label there is no withdrawal, so the PRD-faithful implementation correctly left `chargeback_assessed_cents` at 0. (The already-passing `test_02` fixture publishes a label, confirming the intended chain.) Expected values 47840 and 149000 both recompute correctly under the §3.8 five-step formula.
- `test_16_posture_escalation_occ_and_remediation.py` — `_six_point_substitution_finding`: same missing `publish_case_label`; its trailing `chargeback_status == "ASSESSED"` assertion was unreachable without it.
- `test_15_role_scopes_and_shared_operations.py` — `test_02_a_dealer_may_only_file_documents_against_its_own_lots`: replaced `assert owner["supplier_id"] == …` with `assert owner["lot_id"] == lot_id`. PRD §3.2 declares a `SimpDocument`'s inputs as `lot_id`, `harvesting_vessel_name`, `harvest_date`, `landing_date`, `chain_of_custody_ref` and never gives it a `supplier_id`; §2.1 confirms ownership is derived through *"the `supplier_id` of the lot behind an addressed `SimpDocument`"*. Computed-field silence — the scope-forbidden and `DRAFT`-status assertions (the test's actual subject) were kept.

**Fixes applied to `implementation/`:** none. All 28 failures were test-artifact defects; no implementation check was removed or weakened.

## Step 8: Finalize PRD — 2026-09-02T19:50:00.000Z

Step 8 was NOT skipped: the skip condition requires zero deletions AND zero `test_suite/` fixes AND zero `test_helpers/` fixes AND zero `implementation/` fixes. Step 7 applied fixes in both test layers (only `implementation/` was untouched), so the subagent ran with the verbatim Step 7 worklog entry inlined as `<step_7_diff>`.

### Step 8 subagent summary (verbatim)

Done. `PRD_FINALIZED.md` written with two edits.

## Size
- PRD.md: 448 lines / 12,485 words. PRD_FINALIZED.md: 448 lines / 12,623 words.
- Line delta: 0 (0.0%) — both edits are in-paragraph insertions. Word delta: +138 (+1.11%).

## Changes
- **§2.4 — insert** — one sentence generalising the three-fractional-digit ISO 8601 UTC rendering from `created_at` alone to every timestamp any response carries (`created_at`/`updated_at`, clock-stamped fields, server-derived instants, and client-supplied instants a record echoes back), including normalisation to UTC regardless of submitted offset/precision — `implementation/common.py:33-48` (`iso()`), consumed at `implementation/serializers.py:13-14, 67, 89-91, 112-113, 125-126, 144, 148, 156-157, 179, 194, 208-209, 231-232, 249-250` and `implementation/envelope.py:22`.
- **§3.2 — insert** — one sentence pinning that a `SimpDocument` carries no `supplier_id` of its own and enumerating its projection — `implementation/serializers.py:185-198`.

## Pre-edit search log

**Edit 1 (§2.4 timestamp rendering)**
- (a) Subject: how every timestamp-valued response field is rendered (digit count, timezone normalisation), not just `created_at`.
- (b) Paths enumerated: `common.iso()` (`common.py:33-48`) — the single rendering function, unconditionally `%.03d`-style three digits after `astimezone(utc)`; `common.parse_iso()` (`common.py:51-74`) and `validators.req_datetime` (`validators.py:107-112`) — every client instant is parsed to a UTC-aware datetime before storage, and date-only/offset forms are accepted and normalised; `envelope.build_meta` (`envelope.py:19-26`) for `api_request_timestamp`; all 22 `iso(...)` callsites in `serializers.py` (counter/supplier/species/lot/case_label/ad_item/reading/excursion/sample/simp_document/certification/shrink_event/violation), which covers clock-stamped fields (`received_at`, `cased_at`, `vacated_at`, `published_at`, `withdrawn_at`, `reviewed_at`, `result_recorded_at`, `posted_at`, `reversed_at`, `cured_at`, `expunged_at`), server-derived instants (`excursion.started_at`/`ended_at`, copied from breach-set `reading_at` values in `services.replay_slot_exposure`), and pure client echoes (`reading_at`, `ad_start_at`, `ad_end_at`, `valid_from`, `valid_until`, `harvest_date`, `landing_date`); grepped `isoformat|strftime` across `implementation/` to confirm no alternate rendering path exists (only inside `parse_iso`).
- (c) Adjustments: (i) added the clause "every instant the server copies or derives from another record's timestamp" rather than folding `started_at`/`ended_at` into the clock-stamped list — they are copied from `reading_at`, and §2.4's existing clock-stamped enumeration deliberately excludes them; (ii) added "whenever it is non-null" because `iso(None)` returns `None` and many of these fields are nullable by design; (iii) said "the offset or the fractional precision the client submitted" (not "the format") because `parse_iso` also accepts date-only `%Y-%m-%d`, so a stricter claim about input shape would over-narrow; (iv) scoped the sentence to *rendering* only, so it does not touch which fields exist on `Species`/`IceBedReading` (which have no `updated_at`/`version`).

**Edit 2 (§3.2 SimpDocument projection)**
- (a) Subject: the field set of the `SimpDocument` response projection, specifically whether a derived `supplier_id` appears.
- (b) Paths enumerated: `serializers.simp_document` (`serializers.py:185-198`) — the sole projection, used by all four document endpoints; `routes_docs.create_document` (`routes_docs.py:51-86`) — stores exactly the five submitted inputs plus `status`/`review_note`/`reviewed_at`/`amendment_count`, never a supplier key; `routes_docs.resolve_document` (`routes_docs.py:26-35`) and `routes_docs.create_document`'s scope check — both derive the dealer via `db.lots[...]["supplier_id"]`, confirming ownership flows through the lot; `routes_docs.submit_document` / `review_document` (`routes_docs.py:103-166`) — mutate only `chain_of_custody_ref`, `amendment_count`, `status`, `review_note`, `reviewed_at`, so the field set never grows; `routes_docs.list_documents` (`routes_docs.py:94-100`) — filters on `lot_id` and `status` only, matching §4's "filtered by lot or status"; also checked `routes_lots.py` casing path (`ERR_SIMP_DOCUMENT_MISSING`) which looks documents up by `lot_id`, not by supplier.
- (c) Adjustments: phrased the enumeration as "beyond the common identity, timestamp and `version` fields of §2.4" instead of an absolute closed list, so the sentence stays true to `_common()` adding `id`/`created_at`/`updated_at`/`version`; and wrote "the dealer behind it is always reached through its `lot_id`" rather than restating the §2.1 rule, to avoid re-deriving (and possibly narrowing) the scope check.

## Items deliberately given no PRD edit
- **`test_helpers/factories.py` TypeError (8 failures)** — pure Python plumbing bug: `tilapia_lot_payload`/`snapper_lot_payload` passed variant defaults as keyword args alongside `**overrides`. The variant values themselves (`lot_code`, weights, prices) are fixture data the PRD never constrains. No behavioural choice by the implementation is involved.
- **`test_13` / `test_16` missing `fixtures.publish_case_label(...)` (3 failures)** — PRD §2.10/§3.8 already state the chargeback chain end-to-end, and `implementation/services.py:146-148` + `175-204` match it exactly: `assess_chargeback` is reachable only from `create_shrink_event(..., "MISLABEL_DESTRUCTION")`, which is reachable only from `withdraw_label(..., "SPECIES_MISMATCH", system=True)`. With no `PUBLISHED` label there is no withdrawal and no assessment. PRD determines this uniquely; the tests were missing setup.
- **`test_09:139` `created_at` string mismatch** — the PRD already pins three fractional digits for `created_at`; that site was the test being laxer than the PRD, and Edit 1 covers the rest of the family.

## Step 9: Complete PRD — 2026-09-02T20:15:00.000Z

Orchestrator verification: `wc -l` gives 448 lines for all three of `PRD.md`, `PRD_FINALIZED.md`, `PRD_COMPLETED.md`; heading count is 28 in all three (no section dropped); `PRD_COMPLETED.md` ends on the real §5 boundary `| \`ERR_SUPPLIER_CREDIT_HOLD\` | 402 Payment Required |`. Step 9 edited documentation only — no file under `implementation/`, `test_suite/` or `test_helpers/` was touched — so the orchestrator-verified 8-round green sweep (102/102 × 8, recorded under Step 7) remains the valid test evidence and `results.{1..8}.json` stay on disk as the final artifacts. No re-sweep was needed.

Pipeline is complete: Step 9 has written `workspace/PRD_COMPLETED.md`.

### Step 9 subagent summary (verbatim)

Verification passes: 448 lines (identical to source), 33 diff hunks all 1:1 line replacements (no lines added, dropped, or reordered), section headings at identical line numbers, file ends at the real §5 boundary.

**Line counts / delta:** PRD_FINALIZED.md 448 lines / 93,169 chars → PRD_COMPLETED.md **448 lines / 104,691 chars (+11,522)**. Exact last line:

`| \`ERR_SUPPLIER_CREDIT_HOLD\` | 402 Payment Required |`

**Counts:** 34 changed lines — **30 ambiguity-pins, 4 mismatch-revisions**. Every change is an in-paragraph insert or revision; no new sections or paragraphs.

Mismatch-revisions (PRD said something impl does not do):
- **§2.4 — revise — mismatch** — `version`/`updated_at` settle once per *request*, not per field write; a record created by a request stays at `version` 1; a derived-field re-derivation that changes nothing is not a mutation (PRD had claimed every derived refresh bumps version) — common.py:120-127, services.py:55-72
- **§3.4 — revise — mismatch** — operator withdrawal accepts all five `withdraw_reason` members including `SPECIES_MISMATCH`, and never cascades under any of them (PRD had reasoned "an operator reason is never SPECIES_MISMATCH") — routes_labels_ads.py:133-141, services.py:175-181
- **§3.6 — revise — mismatch** — claim-review `CLEAR` also enforces the counter/supplier/species triple match (`ERR_CLAIM_NOT_SUBSTANTIATED`), not only ACTIVE + validity window — routes_labels_ads.py:290-300
- **§3.9 — revise — mismatch** — allowance ceiling (`ERR_CONVERSION_ALLOWANCE_EXCEEDED`) is tested *before* the `ERR_CONVERSION_NOT_PERMITTED` gate, reversing the prose order — routes_shrink.py:103-112

Ambiguity-pins:
- §2.1 — insert — empty header counts as absent — auth.py:19
- §2.1 — insert — list endpoints apply no ownership comparison and are never scope-narrowed — web.py:83-93
- §2.2 — insert — `api_request_id` is `req_` + 20 uppercase-alnum chars — envelope.py:12-16
- §2.2 — insert — `api_request_timestamp` reads the logical clock — envelope.py:22
- §2.2 — insert — clock capability is the only empty-`data` operation — routes_core.py:39
- §2.3 — insert — blank param = omitted; unparseable/out-of-range `limit`/`offset` → `ERR_INVALID_REQUEST` — envelope.py:83-102
- §2.3 — insert — `created_at` ties broken by creation sequence; unparseable filter value yields an empty page; unknown params ignored — common.py:130, web.py:60-80
- §2.4 — insert — `to_iso8601` parsing and 400 on unparseable — routes_core.py:36-39
- §2.5 — insert — non-string body FK → that type's 404; absent/null FK → 400; unparseable body treated as `{}` — validators.py:150-157, web.py:19-26
- §2.7 — insert — submitted decimals quantised half-up to declared precision rather than rejected; `sampled_weight_g` exempt — validators.py:72-82, routes_samples.py:38
- §3.1 — insert — no uniqueness on `store_number`, `permit_number`, `lot_code` — routes_core.py:46, routes_lots.py:70
- §3.1 — insert — `acceptable_market_names` may be empty and need not contain `market_name`; all three booleans required — routes_core.py:164-167
- §3.2 — insert — cascade cure stamps `cured_at`, leaves `cure_note` null, skips posture re-derivation when nothing was open; `review_note` written null when omitted — routes_docs.py:137-156
- §3.3 — insert — casing legal only from `RECEIVED`; `case_slot` required integer; most-recent-occupant = latest `vacated_at` — routes_lots.py:182,197,208-219
- §3.3 — insert — sales only from `CASED`; `sold_weight_kg` > 0 at 3 dp — routes_lots.py:235-238
- §3.4 — insert — label derivation ignores `label_status` as well as `intake_status` — routes_labels_ads.py:71-86
- §3.5 — insert — filing compares neither validity bound — routes_docs.py:193-196
- §3.5 — insert — approval tests eligibility then `ERR_CERTIFICATION_EXPIRED`; `review_note` written on both decisions, null when omitted — routes_docs.py:242-251
- §3.5 — insert — early `SWEEP` → `ERR_CERTIFICATION_STATE_INVALID`; enforcement `note` lands in `review_note`, omitted leaves prior value — routes_docs.py:266-273
- §3.6 — insert — ad `counter_id` need not equal the lot's; drafting imposes no lot-custody condition — routes_labels_ads.py:171-196
- §3.6 — insert — `COOL_PENDING` precondition; `note` validated and discarded; non-`CASED`/`HELD` lot → `ERR_AD_ITEM_STATE_INVALID`; missing/out-of-enum `rejection_category` → 400 even under `CLEAR` — routes_labels_ads.py:238-251
- §3.6 — insert — `CLAIM_PENDING` precondition; SOD compared before the state test — routes_labels_ads.py:276-286
- §3.6 — insert — missing published label → `ERR_AD_ITEM_STATE_INVALID` after the posture gates; early close → same; retract `reason` is free text and is not stored — routes_labels_ads.py:333-365
- §3.7 — insert — `temperature_c` unbounded; `taken_by_user_id` free text, never compared — routes_cold.py:36-37
- §3.7 — insert — `resolution_note` null when no note supplied — routes_cold.py:113,122
- §3.8 — insert — drawing from a lot in any other `label_status` is allowed and leaves it unchanged — routes_samples.py:62-64
- §3.8 — insert — a retest flip adjusts `lifetime_mismatch_count` (decrement on MISMATCH→MATCH); MATCH always drives `VERIFIED` — services.py:248-266
- §3.8 — insert — relabel recency final tie-break; no `MISMATCH` sample at all → `ERR_RELABEL_SPECIES_MISMATCH` — routes_lots.py:279-288
- §3.8 — insert — `payment_amount_cents` integer ≥ 0 else 400; settlement leaves dealer `status`; `reversal_note` required but not retained — routes_lots.py:312-333
- §3.9 — insert — shrink writable from `RECEIVED`/`CASED`/`HELD` only; a client-written `MISLABEL_DESTRUCTION` event assesses the dealer too — routes_shrink.py:64, services.py:146-147
- §3.9 — insert — full-destruction custody move fires only from `CASED`, comparison reading the pre-decrement weight — routes_shrink.py:158,174-175


