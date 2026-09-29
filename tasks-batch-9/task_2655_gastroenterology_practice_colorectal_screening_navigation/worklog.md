# Worklog — task_2655_gastroenterology_practice_colorectal_screening_navigation

## Step 1: Create task directory — 2026-09-04T01:58:00.000Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2655_gastroenterology_practice_colorectal_screening_navigation` and its `workspace/` subdirectory. Index 2655 was pre-assigned by the orchestrating prompt; no scan of `./tasks/` was performed (concurrent pipelines on this host).

## Step: scaffold generation (SCAFFOLD.yaml + §1.8 + §1.9)
- SCAFFOLD.yaml: 13 entities, 8 state machines (2 parallel dimensions on ScreeningEpisode), 2 concurrency rules, 11 calculations, 38 ordered validations, 56 endpoints, 49 errors, 8 roles.
- SCAFFOLD_DIFFICULTY_DESIGN.yaml: 9 rule_ids x 2 = 18 instances.
- SCAFFOLD_CORNER_DESIGN.yaml: 87 instances across the guide's 9 sections (66 with test recipes + 21 excluded_because stubs).
- scaffold_lint.py: VERDICT clean lint (1010 calls scanned).

## Step 2: Generate scaffold (subagent) — 2026-09-04T03:22:00.000Z

All three scaffold artifacts for task 2655 are complete and lint-clean.

## Output files (all under `/home/ubuntu/github/CodingPRD/tasks/task_2655_gastroenterology_practice_colorectal_screening_navigation/`)

| File | Lines |
|---|---|
| `SCAFFOLD.yaml` | 2654 |
| `SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 1744 |
| `SCAFFOLD_CORNER_DESIGN.yaml` | 4104 |

All three parse under `yaml.safe_load`; `SCAFFOLD.yaml` contains neither `scaffold_difficulty_design` nor `scaffold_corner_design`, and the other two each have exactly one top-level key.

## §1.0–§1.7 counts (SCAFFOLD.yaml)
13 entities · 8 state machines (ScreeningEpisode carries two independent dimensions, clinical + cyclic navigation) · 2 concurrency rules (`session-booking-stale-session` → `expected_session_version`/412, `recommendation-create-stale-episode` → `expected_episode_version`/412) · 11 calculations (2 dual-variant: `claim_pricing`, `adenoma_detection_rate`) · 38 ordered validations · **56 endpoints** · 49 errors · 8 roles. Profile: beyond_expert / temporal_windowing + ledger_reconciliation / graph topology / parallel state machines / segregation_of_duties / immediate.

## §1.8 rule ids (18 instances, 2 each)
`dual_variant_calc`, `combinatorial_formula`, `non_linear_state_machine`, `transitive_cascade`, `priority_pair_validation_conflict`, `boundary_precision_check`, `cross_entity_state_dependency`, `resource_temporal_overlap`, `compensating_invariant`.

## §1.9 sections (87 instances = 66 recipes + 21 `excluded_because` stubs)
entities 12 · state_machines 13 · calculations 12 · validations 20 · endpoints 7 · errors 9 · rbac 5 · cross_cutting_complexity_layers 8 · consistency_model 1.

Every stub cites a §1.8 instance that exists by name, carries no `test_recipe`, and all 105 instance names across the two design files are unique.

## Lint verdict (verbatim)
```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  §1.5 endpoints declared:    56
  §1.1 entities declared:     13
  §1.8 instances scanned:     18
  §1.9 instances scanned:     66
  Calls scanned (§1.8+§1.9):  1010

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```
(`§1.9 instances scanned: 66` counts only recipe-bearing instances; the 21 stubs have no calls.)

Three defects found and fixed on the way to a clean verdict: a capture of the non-existent `QualityPeriod.locked_at` (→ `updated_at`), `basis == PATHOLOGY_FINDINGS` where the enum is `GUIDELINE|OVERRIDE_ATTESTED`, a `risk_tier` payload key that is `source: computed` (→ `family_history_crc`), plus a literal `expected_session_version: "1"` replaced by a captured `${sess_v}`. No sibling task directory was read at any point.

Orchestrator verification: all three files present; `workspace/` intact (re-`mkdir -p`'d defensively per known Step-2 wipe hazard — nothing had been lost).

## Step 3: Copy shared files — 2026-09-04T03:22:30.000Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` → `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD (subagent) — 2026-09-04T03:33:00.000Z

PRD generated at `workspace/PRD.md` — **442 lines**, built incrementally (initial Write + 3 chunked appends + targeted edits), ends at a real section boundary.

## Section list

§1 Introduction · §2.1 Users and RBAC · §2.2 API Response Structure (verbatim) · §2.3 Pagination · §2.4 Common Resource Properties (logical clock, base `2026-08-01T00:00:00Z`) · §2.5 Validation Precedence (all 38 rules in normative order) · §2.6 Nested Path Resolution · §2.7 Optimistic Concurrency on Contended Parents · §2.8 Numeric Precision and Rounding · §2.9 Two-Dimensional Episode State and Cascade Integrity · §2.10 Interval Geometry in the Suite · §2.11 Segregation of Duties · §3.1 Standing Up the Practice · §3.2 Open-Access Referral Triage · §3.3 Opening a Screening Episode · §3.4 Non-Invasive Screening and the Positive-Result Cascade · §3.5 Bowel-Preparation Navigation and the Adherence Score · §3.6 Building the Suite Day: Room Blocks and Anesthesia Coverage · §3.7 Booking, Performing and Abandoning a Colonoscopy · §3.8 Pathology Routing and Surveillance Interval Assignment · §3.9 Two Numbers for the Same Facts: Claim Pricing and Detection Rates · §4 Endpoint Definitions (56 rows) · §5 Error Code Catalogue (49 rows)

## Coverage confirmation (machine-verified by the subagent)

```
Field coverage: entities[].fields 132/132; request_body 77/77; query_params 29/29; path_params 13/13; nested object keys 8/8 — PASS
Rule coverage: 38/38 validations; 2/2 OCC rules; 8 state machines all transitions; 11/11 calculations; 56/56 endpoint side_effects+applies_to; 13/13 entities' defaults/enums; 9/9 sibling-branch symmetry groups — PASS
Path purity (§3 only): 977 backtick tokens scanned, 0 paths, 0 bare HTTP methods — PASS
No operator-syntax leakage, no fuzzy hedges, §4 exactly 4 columns, §5 exactly 2 columns.
```

Neither `SCAFFOLD_DIFFICULTY_DESIGN.yaml` nor `SCAFFOLD_CORNER_DESIGN.yaml` was opened, grepped, or referenced.

Orchestrator truncation check (per known doc-generator failure mode): `tail -25` shows the §5 error table running to a complete final row (`ERR_SESSION_CAPACITY_EXCEEDED | 409`); 49 `ERR_` rows counted, matching the scaffold's 49 errors; 28 headings present. File ends at a real section boundary — no regeneration needed.

## Unit-test generation (test_helpers/ + test_suite/) — complete

- `test_helpers/`: 9 modules, 2154 lines (api_client, api_errors, types, constants,
  factories, fixtures, assertions, test_users, __init__).
- `test_suite/`: conftest.py + 17 numbered test modules, 5405 lines, **119 tests collected**.
- Design coverage: 119 `Design:` tags — 53 queue A (all 18 difficulty instances, each >= 2
  tests) and 66 queue B (all 66 non-stub corner instances, each >= 1 test). No tags point at
  the 21 `excluded_because:` corner stubs. Zero instances skipped.
- Citation pass: every docstring sentence >= 25 chars now survives a literal (whitespace-
  normalized) grep of `workspace/PRD.md`; 38 paraphrased/truncated citations and 1 ellipsis
  were rewritten to full verbatim PRD sentences. Each test carries exactly one `Design:` line
  as the last docstring line.
- Health: `py_compile` clean on all 26 .py files; `pyflakes` clean on `test_suite/`;
  every helper name referenced by the suite resolves through `test_helpers`.
- Nothing was written under `workspace/`; `workspace/implementation/` was never read.

## Step 5: Generate unit tests (subagent) — 2026-09-04T05:20:00.000Z

Test generation is complete and fully verified.

## Files written (task root, nothing under `workspace/`)

`test_helpers/` — 2154 lines: `__init__.py` 40, `api_client.py` 287, `api_errors.py` 112, `assertions.py` 345, `constants.py` 143, `factories.py` 235, `fixtures.py` 502, `test_users.py` 62, `types.py` 528

`test_suite/` — 5405 lines, 18 files: `conftest.py` 54; `test_01_provisional_and_final_pricing_variants.py` 265; `test_02_surveillance_interval_and_line_rounding.py` 194; `test_03_referral_and_episode_state_progression.py` 238; `test_04_pathology_and_positive_result_cascades.py` 271; `test_05_booking_rejection_precedence.py` 190; `test_06_eligibility_and_measurement_boundaries.py` 145; `test_07_cross_entity_state_dependencies.py` 276; `test_08_room_and_anesthesia_contention.py` 230; `test_09_ledger_compensating_invariants.py` 259; `test_10_entity_persistence_and_defaults.py` 475; `test_11_lifecycle_state_machines.py` 465; `test_12_derived_calculations.py` 342; `test_13_validation_rules.py` 579; `test_14_endpoint_behaviour.py` 283; `test_15_error_contract.py` 339; `test_16_role_authorization.py` 386; `test_17_cross_cutting_layers.py` 314

## Tests per queue

- **119 tests collected**, 119 `Design:` tags, one per test.
- **Queue A (Difficulty): 53 tests** — all 18 difficulty instances covered, each with >=2 tests.
- **Queue B (Corner): 66 tests** — all 66 non-stub corner instances covered, each with >=1 test.
- No tag points at a non-existent instance, and none of the 21 corner `excluded_because:` stubs was translated.

## Skipped design instances

**None.** Every non-stub instance in both indices passed the PRD-first two-condition filter and was translated; the only untranslated entries are the 21 corner stubs, which are excluded by design.

## Verification run

- Citation compliance: every docstring sentence >=25 chars survives a literal, whitespace-normalized grep of `workspace/PRD.md` (0 violations). Final pass rewrote 27 docstrings across test_08–test_17, replacing 38 paraphrased/truncated citations and 1 ellipsis with full verbatim PRD sentences.
- Exactly one `Design:` line per test, always last; no ellipses anywhere.
- `py_compile` clean on all 26 generated `.py` files; `pyflakes` clean on `test_suite/`.
- Every helper name used by the suite resolves through `test_helpers`.
- `workspace/implementation/` was never read, and no test directory was created under `workspace/`.

## Step 6: Generate implementation (subagent) — 2026-09-04T04:09:00.000Z

Implementation complete.

## Files written (all under `workspace/implementation/`)

`app.py` 86, `core.py` 289, `validation.py` 215, `calcs.py` 388, `services.py` 384, `routes/__init__.py` 0, `routes/reference.py` 179, `routes/referrals.py` 160, `routes/episodes.py` 295, `routes/tests.py` 67, `routes/sessions.py` 243, `routes/bookings.py` 348, `routes/pathology.py` 89, `routes/recommendations.py` 36, `routes/claims.py` 111, `routes/quality.py` 141 — **total .py 3031**.

Plus `requirements.txt` (`flask>=3.0`) and `start.sh` (executable, reads `$PORT`, binds 0.0.0.0, runs `python3 app.py` in the foreground via `exec`, guarded pip install).

## Endpoint coverage
**56 / 56.** Method+path pairs extracted from the PRD endpoint table and from the registered Flask rules, normalized, `diff` empty — exact match including `POST /_clock/set_current_utc`.

## Architecture notes
- In-memory only: `db = Store()` in `core.py` with 13 dicts + `clock` + `seq`; nothing seeded, so every fresh `start.sh` boot starts empty with the logical clock at exactly `2026-08-01T00:00:00Z`.
- `app.py` registers 10 blueprints, maps `ApiError` → the error envelope, adds 400/404/405/500 handlers so even framework rejections carry the envelope, and wraps the WSGI app in a `threading.Lock` middleware so multi-resource cascades are atomic.
- Money is integer cents with `Decimal` + `ROUND_HALF_UP`, per-line rounding then summation; derived parent fields are always fully recomputed, never incrementally adjusted.

## Smoke test (port 60147, killed by PID resolved from the port)
Boots cleanly; full end-to-end pass succeeded — envelope/auth (401 `ERR_UNAUTHENTICATED`, array envelope with pagination keys); clock set and timestamps derived from it; plan → patient → endoscopist → session (capacity 240) → PUBLISH → episode → booking (OCC `expected_session_version` honored, computed `slot_end_utc`/`occupancy_end_utc`, `planned_classification: SCREENING_PREVENTIVE`); gating errors (`ERR_PREP_NOT_CONFIRMED`, `ERR_INVALID_BOOKING_STATE`); outreach x2 → attestation (`prep_adherence_score` 7.50, `PREP_CONFIRMED`) → check-in → start → complete (2 specimens → `PATHOLOGY_PENDING`) → pathology intake → finalize with the four-hop cascade (report FINALIZED + routed, recommendation at 84 months, episode `CLOSED_SURVEILLANCE_SET`, claim repriced); claim math verified by hand (base 189750 → TIER_2 +8500 → allowed 198250; polypectomy carveout flipped classification to DIAGNOSTIC; patient 119650); claim finalize/dispute ledger round-trip exact to (0,0); quality period lock gating + ADR 1.0 vs benchmark 0.25 → MET; positive non-invasive cascade (new DIAGNOSTIC_FOLLOWUP episode, back-link, patient recomputed to HIGH, 30-day horizon); referral triage and anesthesia coverage/release both behaved.

Every `.py` file compiles under `python3 -m py_compile`; `__pycache__` removed. Server stopped by resolving the listening PID from port 60147 and signalling that PID only — no pattern-based kill.

Orchestrator verification: `test_helpers/` and `test_suite/` are at the task root (no strays under `workspace/`); `workspace/` contains only INSTRUCTION.md, PRD.md, implementation/.

## Step 7: Test/fix iteration loop — 2026-09-04T05:20:00.000Z

Two parallel 8-round stability sweeps (`--isolation per-test-server`, 119 tests, 8 rounds
concurrent per iteration).

- **Iteration 1**: 117/119 in all 8 rounds. Two deterministic failures, both in
  `test_suite/test_14_endpoint_behaviour.py`, both test bugs — no implementation defect found.
- **Iteration 2**: **119/119 in all 8 rounds** (`results.1..8.json`, `passed == total`).

### Fixes applied to `test_suite/`
- `test_14_endpoint_behaviour.py::test_the_coverage_row_survives_the_release_that_demotes_its_block`
  — dropped `coverage_start_utc == "2026-09-15T12:30:00.000Z"` in favour of
  `assert_utc_instant(..., "2026-09-15T12:30:00")`. PRD §2.4 states the three-fractional-digit
  rendering only for `created_at`/`updated_at`; it is silent on whether a client-supplied
  instant such as `coverage_start_utc` is echoed verbatim or re-rendered, so the exact-string
  form was not uniquely derivable (format silence on an input-echoed field).
- `test_14_endpoint_behaviour.py::test_two_identical_creates_straddling_a_clock_write_land_on_different_dates`
  — `assert moved is None` → `assert moved == {}`. PRD §4 states the logical-clock capability
  "returns 200 with an empty `data` object" and §2.2 "For 2xx responses with no data, it
  contains an empty object", so `{}` is the PRD-mandated payload and the old assertion
  contradicted PRD.

No tests deleted. No changes to `test_helpers/` and no changes to `workspace/implementation/`.

## Step 7: Run tests and iterate (subagent, verbatim summary) — 2026-09-04T05:25:00.000Z

Clean 8-round sweep achieved.

**Iterations run: 2** (each = 8 concurrent `per-test-server` rounds, 119 tests, `setsid nohup` wrapped)

- **Iteration 1**: 117/119 in *all 8* rounds — 2 deterministic failures (no flakiness anywhere; the other 117 tests passed in every round).
- **Iteration 2**: **119/119 in all 8 rounds.** Evidence on disk: `workspace/implementation/results.{1..8}.json`, each ~39 KB with `total=119, passed=119, failed=0, errors=0, skipped=0`.

**Tests deleted: none.** Both failures were STEP-2 test bugs, not STEP-1 deletions.

**Fixes applied to `test_helpers/`: none.**

**Fixes applied to `workspace/implementation/`: none.** No implementation defect was found; the implementation was already PRD-faithful on both points.

**Fixes applied to `test_suite/`** (both in `test_suite/test_14_endpoint_behaviour.py`):

1. `test_the_coverage_row_survives_the_release_that_demotes_its_block` — `assert fetched["coverage_start_utc"] == "2026-09-15T12:30:00.000Z"` replaced with `assert_utc_instant(fetched["coverage_start_utc"], "2026-09-15T12:30:00")`. STEP 1c partial-coverage split: PRD §2.4 mandates the three-fractional-digit rendering only for `created_at`/`updated_at`; it is silent on whether a *client-supplied* instant like `coverage_start_utc` is echoed verbatim or re-rendered. A faithful reader may store the input string as given (which this implementation does) or normalize it — not uniquely derivable, so the exact-string form was dropped while keeping the PRD-derivable assertion that the field is an ISO 8601 UTC instant equal to the supplied instant. Scaffold rule: `Corner/endpoints/anesthesia_coverage_create_read_list_and_release`.

2. `test_two_identical_creates_straddling_a_clock_write_land_on_different_dates` — `assert moved is None` → `assert moved == {}`. The old assertion directly contradicted PRD §4 ("the logical-clock capability returns 200 with an empty `data` object") and §2.2 ("For 2xx responses with no data, it contains an empty object"); `validate_success` returns `body["data"]`, so `{}` is the PRD-mandated value. Fix makes the test *more* faithful to PRD. Scaffold rule: `Corner/endpoints/clock_endpoint_reanchors_index_date_and_due_date`.

Housekeeping: `__pycache__`/`.pytest_cache` removed; `test_helpers/` and `test_suite/` are at the task root with no strays under `workspace/`.

Orchestrator independent verification (per known false-clean-sweep hazard): all 8 `results.$i.json` exist, are ~39 KB, and each reports `total=119, passed=119, failed=0, errors=0, skipped=0`.

Step 8 skip decision: NOT skipped — Step 7 ran 2 iterations with 2 `test_suite/` fixes, so the zero-fix skip condition does not hold. Both fixes mark PRD silences (client-supplied-instant rendering; empty-`data` envelope on the clock endpoint) that Step 8 must consider pinning.

## Step 8: Finalize PRD (subagent, verbatim summary) — 2026-09-04T05:15:00.000Z

Done. `PRD_FINALIZED.md` created with exactly one edit.

## Line counts
- PRD.md: 442 lines; PRD_FINALIZED.md: 442 lines (0% line delta — the edit extends an existing paragraph in place; +3 sentences).

## Changes
- §2.4 Common Resource Properties — insert — pins that the three-fractional-digit ISO 8601 rendering applies only to server-minted/derived instants (`created_at`, `updated_at`, `api_request_timestamp`, `finalized_at`, `resulted_at`, outreach `occurred_at`, `slot_end_utc`, `occupancy_end_utc`), while client-supplied instants (`window_start_utc`, `window_end_utc`, `coverage_start_utc`, `coverage_end_utc`, `slot_start_utc`) are persisted and echoed verbatim — `implementation/routes/sessions.py:189-190` (raw `data[...]` stored), `implementation/routes/bookings.py:117` vs `:119-120` (raw vs `iso(...)`), `implementation/core.py:128-138`.

## Per-edit pre-edit search log
Edit 1 (§2.4):
- (a) Subject: rendering/normalization of every instant-valued field the API persists or emits — both client-supplied and server-produced.
- (b) Paths enumerated (grepped `_utc|iso(|now_iso|req_instant|parse_instant` across all of `implementation/`, then read each hit): `core.py:128-146` (`iso`, `now_iso`, `today`), `core.py:149-176` (`parse_instant`, which strips/accepts `Z`, `z`, `+00:00`-family offsets and naive strings), `core.py:229-243` (`new_record`/`touch` → `created_at`/`updated_at`), `core.py:259-263` (`api_request_timestamp`), `validation.py:138-143` (`req_instant` returns a parsed datetime, never writes back a normalized string), `routes/sessions.py:49-50,65-66` (block window instants stored raw), `routes/sessions.py:162-163,189-190` (coverage instants stored raw — the Step 7 site), `routes/bookings.py:54,117` (`slot_start_utc` raw) vs `routes/bookings.py:119-120` (`slot_end_utc`/`occupancy_end_utc` via `iso()`), `routes/tests.py:61` (`resulted_at`), `services.py:296` (`finalized_at`), `routes/episodes.py:177` (`occurred_at`), `routes/reference.py:173-179` (clock endpoint parses `to_iso8601`, persists no string field), plus consumers depending on the verbatim form: `calcs.py:214`, `calcs.py:326` (`slot_start_utc[:10]` for procedure-date attribution), `calcs.py:359,373-374`, `routes/sessions.py:180-181`, `routes/bookings.py:89-90,100-101`.
- (c) Wording adjustments: (i) restricted the exhaustive "verbatim" list to the five instant fields actually persisted from client input, so the clock's `to_iso8601` is not mis-described; (ii) separated the derived booking instants `slot_end_utc`/`occupancy_end_utc` into the three-digit group; (iii) added the closing clause "still interpreted as the instant it denotes wherever a rule in this document compares or offsets it" so verbatim storage is not read as making the stored string the basis of window-containment, overlap, coverage-span, ADR-attribution and `next_due_date` arithmetic; (iv) deliberately said nothing about `YYYY-MM-DD` client-supplied dates (also stored raw) to avoid a claim broader than the Step 7 finding requires.

Step 7 item 2 (`assert moved is None` → `== {}`) needed no PRD change: §4 and §2.2 already uniquely determine it, and `core.respond_empty` (`core.py:271-273`), used by `routes/reference.py:179`, matches that prose exactly. It was a pure test bug.

## Step 9: Complete PRD (three sequential file-partitioned passes) — 2026-09-04T05:35:00.000Z

Orchestrator decision: Step 9 was split into three sequential subagent passes, each partitioned by implementation file, because a single-pass full scan of a 3031-line implementation against a 442-line PRD routinely no-ops (PRD_COMPLETED.md coming back byte-identical to its source). Each pass edited `PRD_COMPLETED.md` in place with the Edit tool; pass 1 owned Step 0 (`cp PRD_FINALIZED.md PRD_COMPLETED.md`).

Partitions: pass 1 = `app.py`, `core.py`, `validation.py`, `routes/reference.py`, `routes/referrals.py`; pass 2 = `calcs.py`, `services.py`, `routes/episodes.py`, `routes/tests.py`; pass 3 = `routes/sessions.py`, `routes/bookings.py`, `routes/pathology.py`, `routes/recommendations.py`, `routes/claims.py`, `routes/quality.py`.

### Totals
- `PRD_FINALIZED.md` 442 lines / 94,463 chars → `PRD_COMPLETED.md` 442 lines / 106,345 chars (+11,882 chars, 0 new lines, 0 new sections; 37 paragraphs revised in place).
- 44 edits total: **39 ambiguity-pins, 5 mismatch-revisions.**
- Integrity: 28 headings intact, 49 `ERR_` rows intact, ends at the `ERR_SESSION_CAPACITY_EXCEEDED` row of §5 (real section boundary); not byte-identical to its source.

### Pass 1 — 11 ambiguity-pins, 0 mismatch-revisions (98,487 chars)
- §2.1 — insert — ambiguity — a present-but-empty auth header counts as absent for `ERR_UNAUTHENTICATED` — validation.py:16
- §2.2 — insert — ambiguity — `api_request_id` is `req_` plus exactly 20 upper-case-alphanumeric characters — core.py:256-262
- §2.3 — insert — ambiguity — `limit`/`offset` must be plain decimal integer literals (whitespace tolerated; sign, leading zero, decimal point, non-digits rejected); empty value falls back to the default — validation.py:164-188
- §2.3 — insert — ambiguity — `created_at` ties broken by insertion order — core.py:249-250
- §2.3 — insert — ambiguity — empty filter treated as absent; non-member enum filter → `ERR_INVALID_REQUEST`; identifier filters compared literally with no FK resolution (empty page, not 404); undeclared query params ignored — validation.py:191-204, routes/reference.py:158-167, routes/referrals.py:81-90
- §2.4 — insert — ambiguity — sub-millisecond logical-clock precision is truncated, not rounded — core.py:128-134
- §2.5 item 3 — insert — ambiguity — JSON `null` treated as absent; strict type checking with no coercion; empty strings rejected unless a subsection gives them meaning; non-JSON/non-object body rejected here while absent/empty body reads as `{}`; accepted date form (exactly 10 chars) and instant forms (`T` required; `Z`/explicit zero offset/no offset read as UTC; non-zero offset rejected) — validation.py:26-158, core.py:149-185
- §3.1 — insert — ambiguity — business-identifier uniqueness (`plan_code`, `npi`, `mrn`) is exact case-sensitive whole-string comparison — routes/reference.py:47-49, 84-86, 122-124
- §3.2 — insert — ambiguity — a new referral's `triage_decision_note` starts null — routes/referrals.py:65
- §3.2 — insert — ambiguity — all four optional triage inputs are shape-validated on every action, but `note` is recorded only by `REQUEST_INFO` (below the ceiling) and the three terminating actions; `updated_asa_class`/`updated_anticoagulant` honoured only by `RESPOND_INFO`; an existing note is never cleared; every accepted action bumps `version` — routes/referrals.py:103-159
- §4 — insert — ambiguity — the logical-clock response carries `response_type` `object` — core.py:271-273, routes/reference.py:179
- §5 — insert — ambiguity — three out-of-catalogue transport failures use the same envelope (`ERR_NOT_FOUND` 404 unrouted, `ERR_INVALID_REQUEST` 405 wrong method, `ERR_INTERNAL` 500 unexpected); trailing slash routes to the same operation — app.py:32, 53-75

### Pass 2 — 14 ambiguity-pins, 1 mismatch-revision (101,882 chars)
- §3.8 — insert — ambiguity — a null `prep_quality_bbps` on the anchoring booking reads as absent, not zero, so the 12-month prep cap does not fire — calcs.py:206
- §3.1 — insert — ambiguity — the `open_episode_count`/`navigation_priority` recompute also runs after booking completion/abort/cancellation and after pathology finalization, and bumps the patient's `version`/`updated_at` only when a value actually changes — services.py:124-137
- §3.8 — insert — ambiguity — anchoring-booking selection rule (cited report's booking; else `COMPLETED` pool → non-`CANCELLED` pool → all, most recently created, ties by insertion order) and `ERR_INVALID_EPISODE_STATE` when the episode holds no booking — services.py:147-153, routes/episodes.py:258-267
- §3.9 — insert — ambiguity — voiding leaves `classification`, `complexity_tier`, `variant`, `reprice_count` as they stood — services.py:202-211
- §3.9 — insert — ambiguity — a new claim also begins with `dispute_reason` null — services.py:177
- §3.8 — **revise** — **mismatch** — a whitespace-only `override_reason` is rejected like an empty one (impl strips before testing) — routes/episodes.py:285
- §3.8 — insert — ambiguity — the recommendation persists `computed_interval_months`, and `override_interval_months`/`override_reason` only as honoured (both null on `GUIDELINE`; a reason supplied without an override is discarded and not non-empty-tested) — services.py:263-265, routes/episodes.py:242
- §3.4 — insert — ambiguity — the positive cascade is exempt from `ERR_DUPLICATE_OPEN_EPISODE` and derives `index_date`/`eligibility_status`/`risk_tier_snapshot` normally with `referral_id` null — services.py:314-318
- §3.4 — insert — ambiguity — the follow-up episode is first observable at `version` 1 with the cascade's `due_date`/`navigation_status` already in place; the test row comes back at `version` 2 — services.py:320-327, routes/tests.py:66
- §3.5 — insert — ambiguity — `acknowledged` defaults to false when omitted or `null` — routes/episodes.py:170
- §3.5 — insert — ambiguity — outreach or attestation after `NAVIGATION_COMPLETE` is rejected with `ERR_INVALID_EPISODE_STATE` — routes/episodes.py:67-68
- §3.5 — insert — ambiguity — outreach only moves an episode in `NOT_STARTED`/`OUTREACH_ACTIVE`/`PREP_AT_RISK`; from `PREP_CONFIRMED` it rescores but leaves `navigation_status` alone — routes/episodes.py:181-186
- §3.5 — insert — ambiguity — attestation rewrites `navigation_status` unconditionally: holds `PREP_CONFIRMED` at >=5.00, drops to `PREP_AT_RISK` from any source below 5.00 — routes/episodes.py:204-207
- §3.3 — insert — ambiguity — neither `referral_id` nor `preceding_episode_id` must belong to the named patient; only the referral's `status` is examined — routes/episodes.py:80-87
- §3.9 — insert — ambiguity — pricing step five reads each line's `allowed_cents` as step three left it, so the first line already carries the complexity addon — calcs.py:261,277

### Pass 3 — 14 ambiguity-pins, 4 mismatch-revisions (106,345 chars)
Pass 2's hand-off mismatch was verified and resolved (`routes/pathology.py:72,81` + `services.py:350-371`: `validate_specimens` returns `[]` for an empty array and `amend_report` assigns it unconditionally, so a report legitimately sits in `AMENDED` with no specimens).
- §3.6 — insert — ambiguity — `room_code` is a non-empty string with no length ceiling and no uniqueness rule; the two window instants are never compared, so a zero-length/inverted window is accepted and yields a zero or negative `capacity_minutes` — sessions.py:47-50,77 / calcs.py:372-375
- §3.6 — insert — ambiguity — `capacity_minutes` discards the partial minute; `booked_minutes` 0 and `remaining_minutes` equals capacity while in `DRAFT`; the `session_date` filter is compared literally, not re-validated as a date — sessions.py:71-79,100-101
- §3.6 — insert — ambiguity — a `reason` on `PUBLISH`/`RESUME`/`CLOSE` is shape-validated then ignored; `suspension_reason` is cleared only by `RESUME` — sessions.py:114,135,147
- §3.6 — **revise** — **mismatch** — coverage may only be assigned to a block in `PUBLISHED` (hence at most one `ACTIVE` row per block), and the supervision ceiling is evaluated **before** the coverage-span rule — sessions.py:168-184
- §3.6 — revise — ambiguity — release admits only a `COVERAGE_CONFIRMED` or `SUSPENDED` block, the row's status is checked before the block's, and the block's `version` increments whether or not the status move occurs — sessions.py:231-242
- §3.7 — insert — ambiguity — `expected_session_version` is unbounded at the shape step, so zero/negative reports `ERR_STALE_SESSION_VERSION`, not `ERR_INVALID_REQUEST` — bookings.py:56,68
- §3.7 — insert — ambiguity — only the two window instants gate containment; `session_date` is never compared to `slot_start_utc` — bookings.py:89-93
- §3.7 — insert — ambiguity — check-in reads neither the block's posture nor the episode's clinical dimension — bookings.py:176-189
- §3.8 — **revise** — **mismatch** — `specimens` is required but may be empty in any of the three statuses, not only `RECEIVED`; an amendment may empty it and leave the report in `AMENDED` with none; each element is normalised to exactly `label`/`histology`/`size_mm`, extra keys discarded — pathology.py:72,81 / services.py:350-371
- §3.8 — insert — ambiguity — finalize and amend read nothing outside the report; no booking or episode state can refuse either — pathology.py:56-60,77
- §3.8 — **revise** — **mismatch** — the four-hop cascade runs against whatever clinical state the episode holds, not only `PATHOLOGY_PENDING` — pathology.py:62-64 / services.py:293-302
- §3.8 — **revise** — **mismatch** — hop three writes `CLOSED_SURVEILLANCE_SET` unconditionally from whichever state the episode held — services.py:302
- §3.8 — insert — ambiguity — `amendment_reason` is not whitespace-tested (unlike an override reason); an omitted `high_grade_dysplasia` takes its false default and clears the earlier flag — pathology.py:73-74
- §3.8 — insert — ambiguity — amendment mutates the report row alone; episode, recommendation and claim (and their `version`s) are untouched until re-finalization — pathology.py:81-88
- §3.9 — insert — ambiguity — every final pass writes `final_classification`, but stamps the booking's `version` only on pathology finalization and client-driven reprice (`touch_booking=True`), not inside abort or no-specimen completion — services.py:184-199 / bookings.py:272 / claims.py:110
- §3.9 — insert — ambiguity — claim finalize and dispute bump the patient's `version`/`updated_at` unconditionally, even for zero amounts — claims.py:69-77,92-100
- §3.9 — insert — ambiguity — a quality window's two dates are never compared, so an inverted window is created and captures nothing — quality.py:33-34
- §3.9 — insert — ambiguity — the overlap test counts existing windows in any `status`, so `LOCKED`/`ATTESTED` windows still block — quality.py:42-50

### Final state
Step 9 wrote `workspace/PRD_COMPLETED.md`. No implementation or test file was modified after the green sweep (all `implementation/` mtimes precede `results.*.json`), so the 8-round 119/119 evidence remains valid for the shipped artifact. `__pycache__` and `.pytest_cache` swept from the task tree. Pipeline complete.
