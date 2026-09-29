# Worklog — task_2640_brand_registry_counterfeit_enforcement

## Step 1: Create task directory — 2026-09-03T23:37:00.000Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2640_brand_registry_counterfeit_enforcement` and `.../workspace`. Index fixed at 2640 by the pre-assigned output directory (no scan of ./tasks/, no auto-allocation) per orchestration instruction.

## Step 2: Generate scaffold — 2026-09-04T01:15:00.000Z

Done — all three scaffold artifacts are complete and the linter is clean.

```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           .../SCAFFOLD.yaml
  Difficulty design:  .../SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      .../SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    70
  §1.1 entities declared:     14
  §1.8 instances scanned:     19
  §1.9 instances scanned:     66
  Calls scanned (§1.8+§1.9):  1129

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

Files (all parse via `yaml.safe_load`):
- `SCAFFOLD.yaml` — 3374 lines, 188,593 B, §1.0–§1.7 only (no `scaffold_difficulty_design` / `scaffold_corner_design` keys)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 1941 lines, 133,271 B, single top-level key `scaffold_difficulty_design`
- `SCAFFOLD_CORNER_DESIGN.yaml` — 3918 lines, 277,599 B, single top-level key `scaffold_corner_design`

Inventory (§1.0–§1.7): `api_prefix: /brand-protection`; 14 entities; 14 state machines / 71 transitions (cyclic shape); 3 OCC concurrency rules; 8 calculations; 3 interval rules; 34 ordered validations + 3 declared conflict pairs; 70 endpoints; 48 errors; 6 roles (segregation_of_duties); complexity layers `optimistic_concurrency, cascading_side_effects, dual_variant_calculation, rate_threshold_triggers`; consistency model `immediate`.

§1.8: 9 rule_ids / 19 instances (dual_variant_calc 2, combinatorial_formula 3, non_linear_state_machine 2, transitive_cascade 2, priority_pair_validation_conflict 2, boundary_precision_check 2, cross_entity_state_dependency 2, resource_temporal_overlap 2, compensating_invariant 2).

§1.9: 84 instances across all 9 taxonomy sections — entities 12, state_machines 14, calculations 14 (6 stubs), validations 16, endpoints 8 (5 stubs), rbac 6, cross_cutting_complexity_layers 6 (2 stubs), consistency_model 1, errors 7 (5 stubs) = 66 executable recipes + 18 `excluded_because` stubs.

Verified beyond the linter with a scripted audit: no duplicate names within §1.9 and no collisions with §1.8; every stub cites an existing §1.8 instance by exact `rule_id / name` and carries no `test_recipe`; every executable instance has all four recipe keys; every `${var}` in payloads, paths and asserts is bound by an earlier `captures:` in the same instance. Only fix needed after the first lint pass was 5 `POST /_clock/set_current_utc` setup calls acting as roles outside that endpoint's §1.5 role list (clock setting is BrandAdministrator / MarketplaceLiaison / CustomsCoordinator only) — repointed to BrandAdministrator (9 call sites normalized). No sibling task directory was read at any point.

## Step 3: Copy shared files — 2026-09-04T01:16:00.000Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` to `workspace/INSTRUCTION.md` (1424 B).

## Step 4: Generate PRD — 2026-09-04T01:35:00.000Z

PRD generation for task 2640 is complete and verified.

## Output
`workspace/PRD.md` — **598 lines, 127,254 bytes**, built with 15 chunked `cat >>` heredoc appends (no single Write, so no 64k truncation exposure).

## Section inventory
- `# Brand Registry & Counterfeit Enforcement API — Product Requirements Document`
- `## 1. Introduction`
- `## 2. Global Specifications & System-Wide Principles` — 2.1 RBAC, 2.2 API Response Structure, 2.3 Pagination, 2.4 Resource Addressing/Identity/Record Metadata, 2.5 Logical Enforcement Clock & Business-Day Deadlines, 2.6 Exact Decimal Arithmetic & Rounding, 2.7 Optimistic Concurrency on Shared Parents, 2.8 Cascade Discipline, 2.9 Order of Rejection
- `## 3. Business Logic & Workflows` — 3.1 Brand Onboarding/Trademark Portfolio/Registry Posture, 3.2 Marketplace Enrolment & Agents of Record, 3.3 Seller Identity/Alias Clusters/Strike Ledger, 3.4 Listing Monitoring & Screening, 3.5 Claims, 3.6 Test Buy Programme, 3.7 Evidence Assembly & Sealing, 3.8 Takedowns/Decisions/Counter-Notices, 3.9 Correspondence/Litigation/Closure, 3.10 Border Enforcement, 3.11 Enforcement Sweep & Brand Metrics
- `## 4. API Endpoint Definitions` — 70-row table, exactly 4 columns
- `## 5. Error Code Catalogue` — 48-row table, exactly 2 columns; file ends here, no audit footer

## Coverage counts
Endpoints 70/70; Errors 48/48; Entities 14/14; State machines 14/14 (52 distinct bare state names); Calculations 8/8; Validations 34/34 (every priority number, error id and HTTP status in the §2.9 ladder); Enum values 78/78; Interval rules 3/3; OCC rules 3/3.

## Requested verification results
- **(a) Clean ending:** `wc -l` = 598; `tail` ends on `| ERR_TEST_BUY_BUDGET_EXCEEDED | 402 |`, the last catalogue row — a real section boundary, not mid-sentence. §4 table: 70 data rows, uniformly 5 pipes (4 columns). §5 table: 48 data rows, uniformly 3 pipes (2 columns).
- **(b) All 70 §1.5 endpoints present:** 0 missing paths, 0 missing table rows.
- **(c) All 48 §1.6 error ids present:** 0 missing.
- **§2.2 fidelity:** `diff` against `section-2.2-response-structure.md` shows only one added trailing blank line — content is byte-verbatim.

## Hard Contract reports
- **Contract 1 — Field-Name Coverage: PASS.** 145 required identifiers (115 entity field names ∪ 109 endpoint input/query/path-param identifiers, deduped) — all 145 appear verbatim inside backticks. 0 missing.
- **Contract 2 — Rule Coverage: PASS.** All 34 validations rendered as an explicit numbered rejection ladder with priority, error id, HTTP status and full applies_to enumeration; all 14 state machines with every transition, actor, precondition and side effect; all 3 OCC rules with field, error, status and serial-observability behaviour; all 3 interval rules with distinct inclusivity/adjacency semantics called out against each other; all 8 calculations with constants, per-step rounding and worked examples in prose (e.g. per-strike rounding 6.28 + 12.58 = 18.86 vs. the wrong 18.85); the segregation-of-duties rule; sibling-branch symmetry documented on all forks (REMOVED/REJECTED, REBUTTED/ACCEPTED/EXPIRED, DIVERSION_CONFIRMED/RELEASED, SETTLED/DISMISSED/NO_ACTION); pinned 6-step sweep order with all 10 output counts.
- **Contract 3 — §3 Path Purity: PASS.** 334 distinct backticked tokens in §3; 0 begin with `/`, 0 are bare HTTP methods, 0 combine method+path, and the literal string `/brand-protection` occurs 0 times anywhere in §3. All 14 path-parameter names are introduced in §2.4 instead.

## Notes / judgement calls
- Two prose fixes applied after the first verification pass: replaced an "as appropriate" hedge in §2.9 priority 15 with the explicit three-way error mapping, and translated a scaffold-sourced `>= 0.8000` in a §4 description into prose ("a `completeness_score` of at least 0.8000").
- Three scaffold uniqueness constraints — (jurisdiction, registration_number), (marketplace_code, seller_ref), (marketplace_code, listing_ref) — have **no dedicated error id** in the 48-error catalogue. Mapped duplicates to `ERR_INVALID_REQUEST` (400) under the priority-3 request-shape gate rather than invent an id.
- The scaffold's state-machine table lists the enrolment-suspend actor as BrandAdministrator | MarketplaceLiaison while the endpoint's roles is [MarketplaceLiaison]; §1.5 treated as authoritative.
- §3 uses 11 subsections rather than the skill's soft 5–9 guideline, because coverage of 14 entities / 70 endpoints dominates the layout suggestion.
- SCAFFOLD_DIFFICULTY_DESIGN.yaml and SCAFFOLD_CORNER_DESIGN.yaml were never opened, grepped or referenced, and no sibling task directory was read.

**Orchestrator verification (independent):** `wc -lc` = 598 lines / 127412 B; `tail -12` ends at the final error row `| ERR_TEST_BUY_BUDGET_EXCEEDED | 402 |`; `grep '^#'` shows all 5 top-level sections and 20 subsections present in order. NOT truncated — no regeneration needed.

## Step 5: Generate unit tests — 2026-09-04T02:31:00.000Z

Generation complete. Both stages are written, statically verified, and audited.

## Locations (task root, not under `workspace/`)
- `test_helpers/` — 9 files, 2167 lines
- `test_suite/` — conftest + 16 test files, 5483 lines
- `workspace/` still contains only `INSTRUCTION.md`, `PRD.md`, `implementation/` (never read or written).

## Coverage audit

**Queue A — `SCAFFOLD_DIFFICULTY_DESIGN.yaml`: 9 rule_ids / 19 instances / 0 stubs → 19 translated, 0 skipped.** Every instance carries >=2 tests: `dual_variant_calc` (2), `combinatorial_formula` (3), `non_linear_state_machine` (2), `transitive_cascade` (2), `priority_pair_validation_conflict` (2), `boundary_precision_check` (2), `cross_entity_state_dependency` (2), `resource_temporal_overlap` (2), `compensating_invariant` (2) — files `test_01`–`test_09`.

**Queue B — `SCAFFOLD_CORNER_DESIGN.yaml`: 84 names - 18 `excluded_because:` stubs = 66 live → 65 translated, 1 skipped.** By section: entities 12/12, state_machines 14/14, calculations 8/8, validations 16/16, endpoints 3/3, rbac 5/6, cross_cutting_complexity_layers 4/4, consistency_model 1/1, errors 2/2. No stub was translated.

**The single skip** (no marker, no placeholder, per the gaps-stay-gaps rule): `rbac/representative_without_the_demanded_scope_cannot_send_a_cease_and_desist`. The PRD does not uniquely derive the outcome — §3.9 says any of `SUBMIT_TAKEDOWN`, `AUTHORIZE_LITIGATION` or `BOTH` satisfies the letter operation (making `ERR_REPRESENTATIVE_SCOPE_INSUFFICIENT` unreachable there), while §3.2 says `AUTHORIZE_LITIGATION` grants only litigation authority (implying refusal). A faithful PRD-only implementer could ship either behaviour.

## Per-file line / test counts

`conftest.py` 51 · `test_01` 137/4 · `test_02` 214/6 (one parametrized x4) · `test_03` 183/4 · `test_04` 213/4 · `test_05` 154/4 · `test_06` 147/4 · `test_07` 185/4 · `test_08` 155/4 · `test_09` 170/4 · `test_10` 529/12 · `test_11` 1011/14 · `test_12` 402/8 · `test_13` 947/16 · `test_14` 277/4 · `test_15` 294/5 · `test_16` 414/6.

**Total: 103 test functions** (~108 collected with parametrization), 398 PRD citation lines.

## Verification results
- `py_compile` clean on all 26 files; `__pycache__` removed.
- Final PRD-citation pass: every `PRD §X.Y: "..."` string is a verbatim substring of `PRD.md` — 0 non-verbatim. Every test docstring carries >=1 citation. All 46 asserted `error_id`s appear in PRD **prose**, not only the §5 table.
- Final Scaffold-citation pass: all 103 tests have exactly one `Design:` line, it is the last docstring line, every tag resolves to a real non-stub instance, no dual tags.
- Zero `skip` / `skipif` / `xfail`; zero scaffold/yaml vocabulary anywhere outside the `Design:` lines.
- Every `test_helpers` import resolves at runtime (0 unresolved); no unused imports.

## Notable input-defect decisions (inputs never edited)
`customs_authority_code` normalized to the PRD enum (`US_CBP`/`EU_TAXUD`, not the recipes' `"CBP"`/`"EUC"`); `round_number` asserted 1 after a successful submit (0 only on DRAFT); `substantiation_score` asserted `0.00` on DRAFT, never null; cease-and-desist success legs pre-escalate the seller via `setup_escalated_seller_via_diversion`. Two recipe orderings were inverted against §2.9 and corrected: the round-cap test now supplies a genuinely new sealed package on the 4th attempt so `ERR_MAX_TAKEDOWN_ROUNDS` (priority 68) is reachable past the mismatch gate (60), and the litigation-segregation refusal was rebuilt with two ACTIVE enrolments so priority 40 isolates from priority 35.

One helper limitation worth flagging to the implementation side: `test_helpers/assertions.py::parse_instant` uses `%Y-%m-%dT%H:%M:%SZ` and cannot parse fractional-second instants, so `test_10`/`test_11` compare timestamps at second precision via local helpers rather than mutating shared infrastructure.

## Step 6: Generate implementation — 2026-09-04T02:03:00.000Z

Implementation is complete and verified.

## Modules (`workspace/implementation/`)

| file | lines |
|---|---|
| `start.sh` (exec, guarded pip install) | 8 |
| `requirements.txt` | 1 |
| `app.py` (4 blueprints, error handlers, request lock) | 61 |
| `db.py` (in-memory store, logical clock) | 87 |
| `errors.py` (48-id catalogue) | 74 |
| `response.py` (envelope + pagination) | 87 |
| `middleware.py` (auth/RBAC, rep identity) | 57 |
| `validation.py` (priority-3 field checks, filters, paging) | 247 |
| `versioning.py` (exactly-once version bump) | 37 |
| `timeutil.py` (ISO-3-digit, business-day walk) | 83 |
| `calc.py` (7 calculations, Decimal HALF_UP) | 236 |
| `ledger.py` (strikes, clusters, cascades, KPIs) | 418 |
| `entities.py` (14 row constructors, field order) | 244 |
| `constants.py` (enums, SLA tables) | 49 |
| `reps.py` (effectivity, scopes, window overlap) | 64 |
| `sweep.py` (6 pinned steps, 10 counters) | 124 |
| `routes/core.py` (clock, brands, registrations, enrollments, reps) | 260 |
| `routes/monitor.py` (sellers, listings, claims, test buys) | 369 |
| `routes/enforce.py` (packages, takedowns, counter notices) | 376 |
| `routes/legal.py` (cases, recordations, investigations, sweep) | 399 |
| `routes/__init__.py` | 0 |
| **total** | **3281** |

## Endpoint coverage
70/70. Machine-diffed every `method` + `path` pair in SCAFFOLD.yaml against Flask's `url_map`: `missing: []`, `extra: []`.

## Error coverage
All 48 catalogue ids are referenced from route/service code (0 unreferenced, 0 ids used that aren't in the catalogue).

## Smoke results
In-process scenario (23 assertions) passed end-to-end, exercising every worked example in the PRD:
- brand DRAFT + budget 500000; enrollment -> brand `ENROLLMENT_PENDING` v2 (OCC parent bump); activate -> `ENROLLED`
- overlapping rep designation -> 409; screen -> `match_score 0.862`, FLAGGED/COUNTERFEIT, price deviation 0.7
- claim preliminary 61.38; substantiate without corroboration -> 422 `ERR_CLAIM_NOT_SUBSTANTIATED` **with nothing persisted** (version still 1)
- test buy fees 735 / billable 5635, brand spend 5635, cooling-period repeat buy -> 409; authenticate COUNTERFEIT -> claim score 96.72 -> SUBSTANTIATED
- evidence package OCC: stale `expected_claim_version` -> 412, correct -> 201; 6 items -> completeness 0.85 -> SEALED
- takedown submit as a non-existent rep -> 404, as the rep -> `decision_due_at 2026-08-07T00:00:00.000Z` (AMZ 5 business days, weekend-correct); screening blocked while pending -> 409
- decision REMOVED -> strike 12.55, seller ACTIVE (no auto-case under 25), claim ENFORCED, listing REMOVED
- counter notice (duplicate -> 409), ACCEPTED -> strike reversed to 0.0, takedown REINSTATED, claim demoted to SUBSTANTIATED
- clock jump to 2027-03-01 -> sweep lapses the registration, suspends the enrollment (`REGISTRATION_LAPSED`), brand -> `ENROLLMENT_LAPSED`; **second sweep returns all-zero counters** (idempotent)
- envelope/pagination/RBAC: `limit=0` -> 400, bad enum filter -> 400, missing headers -> 401, unknown role -> 401, `AuthorizedRepresentative` identity resolves

Live server on `PORT=18640` via `bash start.sh`: booted, bound `0.0.0.0`, returned 201/200/404/403/403-vs-400 correctly with `req_*` ids and `.000Z` timestamps. Killed by PID only; port 18640 confirmed free, no residual PIDs — no pattern kill used.

Storage is in-memory dicts only, clock `2026-08-01T00:00:00Z`, and no non-source files written to disk.

## Step 7: Run tests and iterate — 2026-09-04T03:10:00.000Z

Three iterations of the parallel 8-round stability sweep (`--isolation per-test-server`, all 8 rounds launched concurrently under `setsid nohup`, joined with `wait`, diagnosed only from the per-round `results.$i.json`).

| iteration | total | passed | failed | errors | union of failing tests |
|---|---|---|---|---|---|
| 1 | 111 | 91 | 19 | 1 | 20 (identical in all 8 rounds — no flakiness) |
| 2 | 106 | 105 | 1 | 0 | 1 |
| 3 | 106 | 106 | 0 | 0 | **0 — clean in all 8 rounds** |

No test was deleted: every failing assertion traced to a rule stated verbatim in `PRD.md`, so all 20 were STEP 2 test bugs (three of them fixture/helper bugs with wide blast radius). No implementation change was needed — the server was correct on all 20.

### `test_helpers/` fixes
- `assertions.py::parse_instant` — now accepts both `...SSZ` and `...SS.mmmZ`. PRD §2.4 fixes three fractional digits only for `created_at` / `updated_at` / `api_request_timestamp`; for `ordered_at`, `submitted_at`, `decided_at`, `resolved_at`, `revoked_at`, `cd_sent_at`, every derived deadline and client-supplied window bounds the PRD names no fractional-digit convention, so the rendering is not uniquely derivable and must not be asserted.
- `assertions.py::assert_instant_equals` (new) — compares instants by value, not by rendering. Replaced 26 raw string-equality assertions across `test_02`–`test_09` (12 failing tests). This is STEP 1c partial-coverage handling: the deadline **value** is verbatim in PRD §2.5 and stays asserted; the fractional-digit **format** is not and was dropped.
- `assertions.py::assert_score_2dp` / `assert_score_4dp` — coerce `expected` with `float()`. `substantiation_base()` returns an exact `Decimal`, so `float(actual) - expected` raised `TypeError: unsupported operand type(s) for -: 'float' and 'decimal.Decimal'`.
- `assertions.py::test_buy_pricing`, `factories.py::test_buy_payload`, `factories.py::test_buy_investigation_payload` — marked `__test__ = False`. The PRD's own `test_buy_` vocabulary collided with pytest's `test_` collection prefix: pytest collected all three as test cases through the barrel import, giving 5 phantom items (one hard error, `fixture 'purchase_price_cents' not found`). Collected total drops 111 → 106, which is the true count (103 functions, one parametrized ×4).
- `fixtures.py::fill_and_seal_package` — the mandatory item set is now read off the claim (`claimed_violation_type` from `GET /claims/{id}`) instead of defaulting to `TRADEMARK`. `claim_payload` defaults `claimed_violation_type` to `COUNTERFEIT`, so any test that created a claim with factory defaults built a `TRADEMARK` package against a `COUNTERFEIT` claim and the seal was correctly refused `ERR_EVIDENCE_INCOMPLETE` (422) — a setup failure in 2 tests. PRD §3.7: "Which of those are mandatory depends on the parent claim's `claimed_violation_type`."

### `test_suite/` fixes
- `test_02::test_two_decayed_strikes_of_different_weights_total_1886_not_1885` — fresh total 37.65 → **37.70**. PRD §3.3 puts the removal strike at 12.55 and the seizure-confirmed strike at 25.15, summing to 37.70; 37.65 is the seller-history normaliser, not this sum.
- `test_03::test_rescreen_clears_the_listing_while_enforcement_stays_removed` and `test_04::test_second_removal_propagates_five_levels_and_opens_a_case` — seller status at cluster 12.55 changed `UNDER_INVESTIGATION` → **ACTIVE**. PRD §3.3: "a single fresh takedown-removal strike is 12.55 points and leaves the seller `ACTIVE`"; escalation needs 25.00. Both tests' own later assertions (no case exists yet / the second removal is the escalating one) already assumed `ACTIVE`.
- `test_03::test_enforcement_dimension_advances_while_the_screening_verdict_stands` — listing `violation_type` `TRADEMARK` → **COUNTERFEIT** (2 assertions). The fixture screens at `image_match_score` 1.00, and PRD §3.4's ordered ladder awards `COUNTERFEIT` at image ≥ 0.85 before the `TRADEMARK` branch is consulted ("a listing with an image sub-score of 0.92 ... is `COUNTERFEIT` and never `TRADEMARK`"). The test had conflated the listing's derived `violation_type` with the claim's client-supplied `claimed_violation_type`.

### `implementation/` fixes
None. Storage re-verified as in-memory dicts only (no file I/O, no sqlite, no seeding); `db.py` boots empty with the clock at `2026-08-01T00:00:00Z`.

## Step 7 (orchestrator verification) — 2026-09-04T03:07:00.000Z

The Step 7 subagent deleted its `results.*.json` before exiting, which the deliverable spec requires to be present. Re-ran the full 8-round parallel sweep myself under `setsid nohup` (same flags: `--isolation per-test-server --timeout 120 --test-timeout 30`) to independently confirm the clean-pass claim and to leave the artifacts in place.

Result — all 8 rounds: `total 106, passed 106, failed 0, errors 0, skipped 0`. Wall time ~3.5 min for the concurrent set. `results.1.json` … `results.8.json` now present in `workspace/implementation/`. The clean 8-round sweep is confirmed independently of the subagent's report.

## Step 8: Finalize PRD — 2026-09-04T03:17:00.000Z

Done. `PRD_FINALIZED.md` written with exactly one edit.

## Line counts
- `PRD.md`: 598 lines → `PRD_FINALIZED.md`: 600 lines (+2 lines, **+0.33%**)
- `tail` verified: still ends at `| ERR_TEST_BUY_BUDGET_EXCEEDED | 402 |`

## Changes
- **§2.4 (Resource Addressing, Identity and Record Metadata)** — *insert* — one new paragraph pinning the rendering of every instant-valued response field to ISO 8601 UTC with a trailing `Z` and exactly three fractional-second digits (system-stamped instants, derived deadlines, evidence-item `added_at`, the clock capability's `current_utc`, and client-supplied `effective_from`/`effective_to`, which are normalised on output); sub-millisecond precision truncated, not rounded; the four calendar-date fields explicitly excepted as `YYYY-MM-DD`. — `implementation/timeutil.py:13-25` (sole renderer), `implementation/response.py:33-44`

## Pre-edit search log

**Edit 1 — instant rendering**
- (a) **Subject:** how instant-valued (and date-valued) fields are serialised in every response body.
- (b) **Impl paths enumerated:**
  - `timeutil.py:13-25` `iso()` — the *only* formatter; `%...%02d.%03dZ` with `microsecond // 1000` (truncation), and a `date` fallback to `date.isoformat()`.
  - `grep -rn "iso("` over the whole tree → only 4 callsites: `response.py:29` (`api_request_timestamp`), `response.py:37` (`jsonable` for any `datetime`), `timeutil.py:13` (def), `routes/core.py:31` (`current_utc`). Confirms no second, divergent renderer anywhere.
  - `response.py:33-51` `jsonable`/`public` — recurses into dicts and lists, so the nested `added_at` on evidence items (`routes/enforce.py:81`) is rendered by the same path; `ok`/`created`/`listing`/`error` all funnel through it.
  - `validation.py:136-153` `date_field` / `datetime_field` — both return parsed Python objects, so nothing client-supplied survives as a raw string.
  - `grep -rn "datetime_field|date_field" routes/` — exhaustive list of client-supplied temporal inputs: `to_iso8601` (clock, not persisted), `effective_from`/`effective_to` (`routes/core.py:213,216`, stored as `datetime` in `entities.py:75-76`, therefore re-rendered with 3 digits), and exactly four date fields — `registration_date`/`expiry_date` (`routes/core.py:81-82`, `entities.py:47-48`) and `recorded_on`/`expires_on` (`routes/legal.py:186-187`, `entities.py:214-215`).
- (c) **Wording adjustment:** the first draft said "every temporal field"; the `date_field` enumeration showed that would falsely claim fractional digits for the four calendar-date fields, so the sentence was re-scoped to *instant*-valued fields and an explicit exception clause naming all four date fields was added. "Truncated rather than rounded" was added only after confirming `microsecond // 1000` in the single renderer. `effective_from`/`effective_to` were named explicitly because they are the one client-supplied instant pair that is persisted and echoed, i.e. the normalisation is observable there.

## Items deliberately **not** patched (PRD already determines them)
- `assert_instant_equals` replacing 26 string-equality assertions — the deadline *values* are verbatim in §2.5; only the format was unpinned, and that is now covered by the single edit above.
- `assert_score_2dp`/`assert_score_4dp` `float(expected)` — pure helper type bug. The helpers already asserted `isinstance(actual, (int, float))` both before and after the fix, so the JSON-number type of score fields was never the ambiguity; `response.py:34` (`Decimal → float`) is consistent with it, so no PRD text was needed.
- `__test__ = False` on `test_buy_pricing` / `test_buy_payload` / `test_buy_investigation_payload` — pytest collection-prefix collision, no product behavior.
- `fill_and_seal_package` reading `claimed_violation_type` off the claim — §3.7 already states "Which of those are mandatory depends on the parent claim's `claimed_violation_type`" and lists all three sets.
- `37.65 → 37.70` — §3.3 already pins bases 12.55 / 25.15 (`ledger.py:12-13`) and 37.65 is separately pinned as the seller-history normaliser (`calc.py:106`); both verbatim in PRD.
- Seller `ACTIVE` at cluster 12.55 — §3.3 states it verbatim; thresholds 25.00 / 60.00 verified at `ledger.py:21-22`.
- `violation_type` `COUNTERFEIT` at image 1.00 — §3.4's ordered ladder and its "image 0.92 ... is `COUNTERFEIT` and never `TRADEMARK`" example already determine it.
- No `implementation/` changes were listed in the diff, so nothing else was in scope.

## Step 9: Complete PRD — 2026-09-04T03:44:00.000Z

Run as **three sequential file-partitioned passes** over a single `PRD_COMPLETED.md` (orchestrator seeded it with `cp PRD_FINALIZED.md PRD_COMPLETED.md`, then each pass edited in place with the Edit tool only). Rationale for splitting: a single-pass Step 9 over 3281 lines of implementation reliably under-scans and can silently no-op, leaving PRD_COMPLETED.md byte-identical to its source. Partitioning also bounds each subagent's context so no pass needs to hold the whole codebase.

Partitions: pass 1 = app/db/errors/response/middleware/validation/versioning/timeutil/constants/entities + routes/core.py; pass 2 = calc.py/reps.py + routes/monitor.py; pass 3 = ledger.py/sweep.py + routes/enforce.py + routes/legal.py.

### Totals
- `PRD_FINALIZED.md` 600 lines / 128,207 chars → `PRD_COMPLETED.md` 600 lines / **142,978 chars (+14,771)**. All edits in-paragraph; no new lines, no new sections.
- **59 edits total: 49 ambiguity-pins, 10 mismatch-revisions.** md5 differs from PRD_FINALIZED.md (`ab61a431…` vs `7ab0a400…`) — the scan demonstrably ran.
- Integrity re-verified by orchestrator: 28 headings, §4 table 70 endpoint rows, §5 table 48 error rows, tail still ends at `| ERR_TEST_BUY_BUDGET_EXCEEDED | 402 |`, `diff` vs PRD_FINALIZED shows 57 changed-line groups.

### Pass 1 (12 ambiguity-pins, 1 mismatch-revision)
- §2.1 — insert — ambiguity — present-but-blank `X-User-ID`/`X-User-Role` counts as absent → `ERR_UNAUTHENTICATED` — middleware.py:44
- §2.1 — insert — ambiguity — `AuthorizedRepresentative` identity resolution sits between priority 2 and 3 — middleware.py:53-56
- §2.2 — revise — ambiguity — `api_request_id` is `req_` + exactly 20 uppercase-alphanumeric chars — response.py:22-23
- §2.2 — revise — ambiguity — `api_request_timestamp` read from the logical clock, not wall time, on success and error alike — response.py:29
- §2.3 — insert — ambiguity — free-form filters accept any string and match nothing; undocumented query params ignored, not rejected — validation.py:178-200
- §2.4 — insert — ambiguity — client instants: `±hh:mm` converted to UTC; no-offset/no-`Z` taken as already UTC — timeutil.py:50-55
- §2.5 — revise — ambiguity — `to_iso8601` mandatory, replaces the clock outright (windable backwards); 200 with `data.current_utc` only — routes/core.py:25-31
- §2.6 — insert — ambiguity — decimals emitted as bare JSON numbers with fractional trailing zeros dropped (`0.8620`→`0.862`) — response.py:33-35
- §2.9 (pri 3) — insert — ambiguity — matcher sub-scores accepted as JSON number or decimal string at any precision — validation.py:101-123
- §3.1 — insert — **mismatch** — (`jurisdiction`,`registration_number`) uniqueness runs *after* `brand_id` resolution, so unknown brand + duplicate pair yields `ERR_BRAND_NOT_FOUND` — routes/core.py:85-93
- §3.2 — insert — ambiguity — `asserted_registration_id` must resolve but need not belong to the enrolling brand — routes/core.py:132,175-182
- §3.2 — insert — ambiguity — one enrolment create supersedes *every* `SUBMITTED`/`SUSPENDED` sibling on that marketplace in one pass — routes/core.py:142-144
- §3.2 — insert — ambiguity — revoke `reason_code` free-form 1–80; re-revoking is `ERR_INVALID_STATE` (409) — routes/core.py:253-256

### Pass 2 (10 ambiguity-pins, 4 mismatch-revisions)
- §2.9 pri 3 — revise — mismatch — corrects pass 1's "never rounded" claim: the shape gate accepts any precision, §3.4 rounds — routes/monitor.py:143
- §2.7 — insert — ambiguity — `expected_canonical_seller_version` only type-checked; negative/zero yields 412 not 400 — routes/monitor.py:66
- §3.3 — revise — mismatch — `seller_ref` not blank (whitespace-only refused) — routes/monitor.py:32, validation.py:44
- §3.3 — insert — ambiguity — alias and canonical `version` bump unconditionally; the 200 returns the alias row — routes/monitor.py:78-82
- §3.4 — revise — mismatch/ambiguity — `listing_ref` not blank; (marketplace_code, listing_ref) uniqueness runs last, after brand/seller resolution — routes/monitor.py:100-106
- §3.4 — revise — mismatch — sub-scores rounded half-up to 4 places before persisting and before the composite and ladder (0.84995 → 0.8500 → COUNTERFEIT) — routes/monitor.py:143
- §3.5 — revise — ambiguity — no brand/listing cross-ownership check; duplicate-live-claim `ERR_INVALID_STATE` precedes `ERR_LISTING_NOT_FLAGGED` — routes/monitor.py:161-169
- §3.5 — insert — ambiguity — `NONE → CLAIM_OPEN` fires only from `NONE`; `REMOVED`/`REINSTATED` untouched and unversioned — routes/monitor.py:177-179
- §3.5 — insert — ambiguity — `registration_strength` re-derived and re-persisted with `substantiation_score`; empty body accepted — routes/monitor.py:208-215
- §3.5 — insert — ambiguity — dismissal `reason_code` mandatory 1–80, not blank, validated but never stored — routes/monitor.py:223
- §3.6 — insert — ambiguity — only claim-state gate on ordering is "not `DISMISSED`" — routes/monitor.py:250
- §3.6 — insert — ambiguity — counterfeit branch re-persists `registration_strength`; claim untouched when recompute reproduces both values — routes/monitor.py:328-333
- §3.6 — insert — ambiguity — authentic branch: already-`DISMISSED` claim keeps reason/version; `enforcement_status` forced to `NONE` from any value; match figures survive; listing touched only on change — routes/monitor.py:337-349
- §3.6 — insert — ambiguity — cancellation `reason_code` mandatory 1–80, discarded — routes/monitor.py:358
- §3.7 — revise — mismatch — duplicates collapse only for *mandatory* types; a repeated supporting type counts per item — calc.py:228

`reps.py` needed no patches — half-open effectivity, `BOTH`-intersects-everything scope algebra, DESIGNATED-peer overlap scan and adjacency-allowed comparison are all already uniquely pinned by §3.2 and §2.9 priorities 30/35/70.

### Pass 3 (27 ambiguity-pins, 5 mismatch-revisions)
- §2.7 — insert — ambiguity — `expected_claim_version` not range-checked; negative/zero fails the equality test, not the shape gate — validation.py:72 via enforce.py:48
- §3.2 — revise — **mismatch** — suspension cascade re-derives brand posture unconditionally, bumping `version` even when unchanged (contradicted §2.8's no-change rule) — ledger.py:215-217
- §3.3 — insert — ambiguity — a strike effective after a backwards-wound clock has negative age and counts as fresh at full weight — ledger.py:81
- §3.7 — insert — ambiguity — no state gate on the parent claim at package create; a `DISMISSED` claim accepts a new package — enforce.py:49
- §3.7 — insert — ambiguity — sealing a non-`ASSEMBLING` package is `ERR_INVALID_STATE`, not the sealed-package error — enforce.py:94
- §3.7 — insert — ambiguity — withdrawal `reason_code` mandatory 1–80, validated then discarded — enforce.py:110
- §3.8 — insert — ambiguity — filing advances the listing only from `CLAIM_OPEN` — enforce.py:198
- §3.8 — insert — ambiguity — refiling overwrites the listing to `TAKEDOWN_PENDING` from any value, touched only on change — enforce.py:282
- §3.8 — insert — ambiguity — withdrawal also demotes `ENFORCED` claims on the released listing, for all three triggers — ledger.py:280, sweep.py:29
- §3.8 — insert — ambiguity — non-`APPROVED_REMOVED` counter-notice target is `ERR_INVALID_STATE` ahead of window/duplicate; `seller_id` not cross-checked against the listing's seller — enforce.py:299
- §3.8 — insert — ambiguity — `rebuttal_ref` shape check precedes the 404; sent with `ACCEPTED` it is ignored and stays null — enforce.py:342,364
- §3.8 — insert — ambiguity — no case is auto-created by the reversal cascade — enforce.py:375 (`auto_case=False`)
- §3.9 — insert — ambiguity — no escalation, cluster-root or duplicate-open-case check on the manual case path — legal.py:26-35
- §3.9 — insert — ambiguity — cease-and-desist requires no `ACTIVE` enrolment and no brand match on the acting designation (scope check accepts all three enum values, exactly as §3.9 already said) — legal.py:66-76
- §3.9 — insert — ambiguity — `response_ref` 1–80 validated not stored; both gates `ERR_INVALID_STATE`; no `case_status` gate, so a `CLOSED` case at `CD_SENT` still accepts an answer — legal.py:91-98
- §3.9 — insert — ambiguity — CD-ignored sweep selects on `correspondence_status` alone (closed/in-litigation cases still move); case bumps in step 3, seller in the step-5 recompute — sweep.py:95-103
- §3.9 — insert — ambiguity — `court_code` 1–40 validated, never persisted — legal.py:143
- §3.9 — insert — ambiguity — `closure_note` 1–200 validated/not persisted; already-`CLOSED` is `ERR_INVALID_STATE` before the per-outcome gates — legal.py:158-161
- §3.10 — insert — ambiguity — no brand/registration cross-ownership check at recordation create — legal.py:191-192
- §3.10 — revise — **mismatch** — dropped non-existent `OPPOSED`/`ABANDONED` statuses from the eligibility sentence — constants.py:13
- §3.10 — insert — ambiguity — a `DRAFT`/`EXPIRED` recordation on a `BORDER_SEIZURE` investigation is `ERR_INVALID_STATE` — legal.py:307
- §3.10 — insert — ambiguity — fields the source kind does not use are ignored and never resolved, so they yield no 404 — legal.py:286-295
- §3.10 — insert — ambiguity — evidence submission requires `OPEN`, else `ERR_INVALID_STATE`, checked before window/traceability — legal.py:350
- §3.10 — revise — ambiguity — "no live case" pinned to `case_status` `OPEN` only, and the seller must have moved out of `ACTIVE` in that recompute — ledger.py:151,191
- §3.11 step 1 — revise+insert — ambiguity — `expiry_date` strictly before the clock's date; plus the orphaned-`SUBMITTED`-notice pass inside step 1 that feeds `withdrawn_takedown_count` — sweep.py:42,58-67
- §3.11 step 2 — revise — ambiguity — takedown counted only when it was `COUNTER_NOTICED`; listing moves only from `REMOVED`; claim demotion conditional — sweep.py:83-92
- §3.11 step 4 — revise — ambiguity — `expires_on` strictly before the clock's date — sweep.py:109
- §3.11 steps 5/6 — insert — ambiguity — one combined recompute; exact semantics of `blocked_seller_count` / `escalated_seller_count` / `deescalated_seller_count` (`ACTIVE → BLOCKED` counts only as blocked; per-member counting; points-only changes counted nowhere) — sweep.py:116-123
- §3.11 metrics — revise — **mismatch** — "all four of the latter" → "all five" (five integer fields returned) — ledger.py:411-418
- §3.11 — insert — ambiguity — `repeat_infringer_count` threshold reads the stored `cluster_strike_points`, not a read-time decay recompute; attributability from the live strike set — ledger.py:401-404
- §4 `POST /takedowns` — revise — **mismatch** — table claimed ACTIVE/SUBSTANTIATED/SEALED gates at draft time; only registration-eligibility and same-claim apply — enforce.py:130-137
- §4 `POST /cases` — revise — **mismatch** — table claimed "against an escalated seller"; no such check exists — legal.py:26-35

### Post-Step-9 confirmation sweep
Step 9 touched only PRD prose, never `implementation/` or the tests, but a final 8-round parallel sweep was run under `setsid nohup` to leave the deliverable's `results.{1..8}.json` in their final state. All 8 rounds: `total 106, passed 106, failed 0, errors 0, skipped 0`.

**Pipeline complete.** `workspace/PRD_COMPLETED.md` written.
