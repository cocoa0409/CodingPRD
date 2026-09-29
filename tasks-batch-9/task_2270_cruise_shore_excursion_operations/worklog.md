# Worklog — task_2270_cruise_shore_excursion_operations

## Step 1: Create task directory — 2026-09-01T00:00:00.000Z

Created `tasks/task_2270_cruise_shore_excursion_operations/` and `tasks/task_2270_cruise_shore_excursion_operations/workspace/` (directory name pre-allocated by the caller; no index scan performed).

## Step 2: Generate scaffold — 2026-09-01T16:35:00.000Z

All three artifacts are complete and lint-clean.

## Files (all at `/home/ubuntu/github/CodingPRD/tasks/task_2270_cruise_shore_excursion_operations/`)

**`SCAFFOLD.yaml`** (4332 lines, §1.0–§1.7 only — no `scaffold_difficulty_design` / `scaffold_corner_design` keys)
- 14 entities, 9 state machines (2 of them parallel dimensions on `Booking`), 3 concurrency rules, 12 calculations, 47 ordered validations, 58 endpoints, 59 errors, 7 roles
- `complexity_profile`: `primary_archetype: quota_allocation`, `secondary: temporal_windowing`, layers `[optimistic_concurrency, cascading_side_effects, dual_variant_calculation, selector_policy]`, `role_model: segregation_of_duties`, `difficulty_level: beyond_expert`
- One consistency fix made this session: validation priority 7's enumerated 404 list was missing `ERR_AUDIT_NOT_FOUND` and `ERR_LEDGER_ENTRY_NOT_FOUND` (both declared in §1.6 as path-id 404s); added.

**`SCAFFOLD_DIFFICULTY_DESIGN.yaml`** (2956 lines) — 25 instances across all 9 §0.5 rules (2/3/3/2/4/4/3/2/2), ≥2 per rule.

**`SCAFFOLD_CORNER_DESIGN.yaml`** (7138 lines, regenerated from scratch) — 103 instances over all 9 claim-extraction-guide sections: entities 16, state_machines 17, calculations 18, validations 15, endpoints 6, errors 20, rbac 5, complexity_layers 5, consistency_model 1. 75 carry full `test_recipe`s; 28 are `excluded_because:` stubs citing §1.8 instances by name.

## Audit results
- `python3 skills/prd-bench-scaffold-generator/scaffold_lint.py tasks/task_2270_cruise_shore_excursion_operations`:
```
Coverage
  §1.5 endpoints declared:    58
  §1.1 entities declared:     14
  §1.8 instances scanned:     25
  §1.9 instances scanned:     75
  Calls scanned (§1.8+§1.9):  1572

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```
- Error catalog: all 59 error ids triggered by a §1.9 instance or cited via a stub; zero unreferenced.
- Endpoint coverage: 58/58 §1.5 endpoints exercised by at least one structured call across the two design files (the last gap — 11 collection listings — was closed by adding a paginated-envelope instance rather than by weakening the corner).
- 103 corner names + 25 difficulty names are unique across the union; every `excluded_because.difficulty_instance` resolves to an existing §1.8 name; no stub carries a `test_recipe`.
- No forbidden concurrency vocabulary anywhere; all OCC tokens are `${var}` captures, never literals.
- The hard constraint held: no sibling `task_*/` directory was listed, read, or grepped — the scaffold came only from the verbatim scenario line plus the skill spec and its claim-extraction guide.

## Step 3: Copy shared files — 2026-09-01T16:35:30.000Z

Copied `./INSTRUCTION.md` → `tasks/task_2270_cruise_shore_excursion_operations/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-09-01T16:52:00.000Z

The PRD is written and all three hard contracts pass.

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_2270_cruise_shore_excursion_operations/workspace/PRD.md` — 467 lines.

**Structure**
- `# Cruise Shore Excursions API — Product Requirements Document`
- `## 1. Introduction` (3 paragraphs)
- `## 2. Global Specifications & System-Wide Principles` — 10 subsections: 2.1 RBAC, 2.2 API Response Structure (pasted byte-verbatim from `section-2.2-response-structure.md`, verified by exact substring match), 2.3 Pagination, 2.4 Resource Identity / Mutation Counters / Append-Only Records, 2.5 The Logical Clock, 2.6 Cents / Basis Points / Rounding Discipline, 2.7 Stale-Read Protection, 2.8 The Order in Which Objections Are Raised (full 47-priority ladder), 2.9 Path Resolution and the 404 Vocabulary, 2.10 Segregation of Duties
- `## 3. Business Logic & Workflows` — 9 domain-derived subsections (ports/meeting points/port calls; operator vetting and safety scoring; catalog; departure scheduling with congestion, tender waves and timing risk; selling with eligibility screen, pricing and channels; ticketing/check-in/dispatch/return guarantee; cancellations, refunds and alternative offers; incidents and liability claims; commission settlement and revenue reporting)
- `## 4. Endpoint Definitions` — intro paragraph on 201 vs 200, then 58 rows, exactly 4 columns
- `## 5. Error Code Catalogue` — 59 rows, exactly 2 columns. File ends here (no audit footer written to disk)

**Contract 1 — Field-Name Coverage: PASS.** 162 required identifiers (140 entity field names incl. common `id`/`created_at`/`updated_at`/`version`, all endpoint `input` names, all 17 dict-output keys of the revenue report and clock endpoints, all 14 path params). 0 missing. Verification stripped fenced code blocks before backtick extraction.

**Contract 2 — Rule Coverage: PASS.**
- Validation ordering: all 47 priorities stated in ascending order in §2.8 with explicit priority numbers; all 59 error ids appear in §1–§3 prose (not merely in the §5 table).
- Concurrency: all 3 OCC rules in §2.7 with exact field names (`expected_departure_version`, `expected_operator_version`), exact error ids and 412; plus the explicit statement that no other operation accepts a version field.
- Cross-entity side effects: all 95 endpoint `side_effects` narrated, including CASCADE-A (operator suspension, four hops), CASCADE-B (delay → RED → close → void), CASCADE-C (port call cancel → weather refunds), operator-termination archiving, statement-supersede voiding, and claim `ADJUDICATED_UPHELD → SETTLED` on final settlement.
- `applies_to` scopes: every multi-endpoint rule names all its guarded operations (e.g. `ERR_INVALID_TIME_WINDOW` across 7 operations, `ERR_NO_ELIGIBLE_TENDER_WAVE` across 3, `ERR_OPEN_CLAIM_BLOCKS_ISSUE` across statement transitions and vetting actions, `ERR_NO_ALTERNATIVE_AVAILABLE` across cancellation and catalog actions).
- Field-level content: every enum value of every field appears verbatim (0 missing), all defaults and ranges stated, all 12 calculations' numeric constants present in prose (mechanically checked, 0 missing), plus `LEVEL4_EXCLUDED_FLAGS`.
- Sibling-branch symmetry: WEATHER vs OPERATIONAL cancellation forks stated side by side with the three differences; PROVISIONAL vs FINAL commission bases; the two adjudication source states declared identical; the two settlement source states declared identical.
- Tail: all 63 transitions across the 9 state machines covered with preconditions and side effects.

**Contract 3 — §3 Path Purity: PASS.** 1139 backticked tokens in §3 (367 unique); zero start with `/`, zero are bare HTTP methods, zero are method+path. Endpoints in §3 are referenced by state-transition framing, role plus action verb, or capability description. Paths appear only in §1 (the `/shore-excursions` prefix) and §4.

**Notes:** two endpoint descriptions carried scaffold-internal references (`per calculations.revenue_report_per_port`, `using calculations.tender_wave_selection`); both were reworded in the §4 table so no internal seed-table naming leaks. `SCAFFOLD_DIFFICULTY_DESIGN.yaml` and `SCAFFOLD_CORNER_DESIGN.yaml` were never opened, grepped or referenced.

## Step 5: Generate unit tests — 2026-09-01T17:35:00.000Z

Complete. Test infrastructure and suite are on disk and the audit is clean.

## Files created

**Stage 1 — `test_helpers/` (9 files, 2 559 lines)**
- `types.py` — roles, ~35 str-Enums, 14 TypedDicts (append-only shapes deliberately carry no `updated_at`/`version`)
- `api_client.py` — `ApiClient(GenericApiClient)`, `PREFIX="/shore-excursions"`, one method per all 58 endpoints + `set_clock()`
- `api_errors.py` — 59-member `ApiErrorId` + `HTTP_STATUS_CODES`, registered via `set_error_http_status_map`
- `constants.py` — every pinned figure from the PRD's calculations (tier multipliers, discount cap 1200 bps, service fee 300 bps/cap 1500, refund tiers 4320/1440/180 → 10000/7500/5000/0, 2880-minute pre-cruise release, banding 0/45, audit weights, score floor 60, rebate tiers, …) plus canonical instants
- `test_users.py`, `factories.py` (13 entity payload builders + `without()` + `REQUIRED_FIELDS`/`OPTIONAL_FIELDS`), `assertions.py` (shape, common-field, and the PRD's conservation invariants), `fixtures.py` (48 granular steps + 14 composite worlds), `__init__.py`
- `test_suite/conftest.py` — session `api` fixture + 10 role-header fixtures

**Stage 2 — `test_suite/` (10 files, 5 849 lines, 142 tests)**

| file | tests |
|---|---|
| test_difficulty_calculations.py | 14 |
| test_difficulty_state_machines_and_cascades.py | 11 |
| test_difficulty_precedence_and_boundaries.py | 20 |
| test_difficulty_dependencies_and_invariants.py | 15 |
| test_corner_entities.py | 15 |
| test_corner_state_machines.py | 19 |
| test_corner_calculations.py | 11 |
| test_corner_validations.py | 11 |
| test_corner_endpoints_and_errors.py | 17 |
| test_corner_rbac_layers_and_consistency.py | 9 |

Queue A: 60 tests over 25 instances. Queue B: 82 tests over 75 non-stub instances.

## Coverage audit (mechanical, over both design yamls)
- Queue A: 25/25 instances have >=2 tests.
- Queue B: 75/75 non-stub instances have >=1 test.
- 28 `excluded_because:` stubs: **0** tests emitted against any of them; all 28 `difficulty_instance:` cross-references verified to resolve to a real queue-A instance.
- 142/142 tests carry exactly one trailing `Design:` line, last in the docstring, resolving to a real instance; 0 untagged, 0 dual-tagged, 0 unresolvable.
- 437 PRD quotes, each confirmed by literal `grep -F` against `workspace/PRD.md` (0 wrapped/normalised, 0 failures).
- Scaffold-vocabulary pass: no occurrence of scaffold/design-index/§1.x/Table-N vocabulary anywhere in emitted code (the `Design:` tag excepted).
- All 19 Python files compile; every `fixtures.*`/`factories.*`/`assertions.*`/`api.*`/`ApiErrorId.*` reference and every string dict key used in the suite statically resolves.

## Instances skipped: none
All 100 non-stub instances passed the PRD-first two-condition filter. Three individual *recipe assertions* were dropped as not uniquely derivable (the instances still have tests): a `TourOperator.version == 2/3` expectation (PRD never says whether recording an audit bumps the operator row — replaced by a no-drift check), seat-bucket counts after the pre-cruise release has already fired, and a `safety_score` value asserted outside the scoring test.

## Design-yaml defects found (PRD trusted, per the brief)
1. Recipes use `audit_type` values `PERIODIC` / `INCIDENT_FOLLOW_UP`; PRD §3.2 declares only `INITIAL`, `ANNUAL`, `INCIDENT_TRIGGERED` -> substituted.
2. Cascade-B annotates pre-delay `slack_minutes_actual` as 75; PRD derives **65** -> asserted 65.
3. One recipe files an incident against a `TICKETED` booking, which §3.8 forbids -> world rebuilt to `CHECKED_IN`.

## Stage 1 defects found and fixed during generation
- `assert_seat_conservation` — broke after the 2880-minute pre-cruise release; now takes `precruise_released` and floors both effective figures at 0.
- `assert_money_conservation` — cannot hold while `financial_status` is `AUTHORIZED`; now branches.
- `assert_statement_waterfall` — contradicted PRD §3.9: it subtracted a spurious `refunds_cents`, omitted the zero floor, and subtracted `rebate_cents` (which the PRD stores negative). Now `payable_pre_rebate = max(0, gross − port_fee − commission − claim_offset − penalty)` and `operator_payable = payable_pre_rebate + rebate + adjustment`.
- `setup_checked_in_booking` ordered `ARRIVE` before the clock move, but PRD line 166 permits arrival only once the clock has reached `effective_arrival_utc`; the clock move now precedes it, and the five composites layered on it (`setup_operating_departure`, `setup_completed_departure`, `setup_incident`, `setup_claim`, `setup_claim_under_review`) no longer default `checkin_clock=None` — they default to the new `INSTANTS["CHECKIN_CLOCK"]` (`2026-09-15T08:30:00Z`, past arrival and inside the check-in window).

Nothing under `workspace/implementation/` was read or written at any point.

## Step 6: Generate implementation — 2026-09-01T17:35:30.000Z

Implementation complete and verified.

## Location
`workspace/implementation/`

## Module layout (~3,760 lines, all hand-written, no test files read)
- `start.sh` (executable, `0755`) — guarded `pip install flask` only if `import flask` fails, then `exec python3 app.py`. `app.py` binds `0.0.0.0:${PORT:-10000}`, `threaded=True`. `requirements.txt` pins `flask==3.0.3`.
- `app.py` — registers 11 blueprints, `strict_slashes = False`, error handlers for `ApiError`, `HTTPException` (404/405/400 → `ERR_VALIDATION`) and bare `Exception`.
- Core: `db.py` (in-memory dicts, logical clock, `insert`/`touch`/`ordered`), `errors.py` (59 error ids + HTTP statuses), `response.py` (meta envelope, `req_` + 20 uppercase alnum), `middleware.py` (`X-User-ID`/`X-User-Role`, 401 then 403), `validation.py` (typed field specs, pagination, `*_or_404` helpers), `serializers.py` (14 field tuples), `util.py` (instant parsing, `Decimal` half-up, bps math).
- `services/` (12): `timing`, `allocation`, `pricing`, `eligibility`, `safety`, `ledger`, `commission`, `occupancy`, `tender`, `alternatives`, `cascades`, `revenue`.
- `routes/` (11 + `__init__.py` holding `API_PREFIX = "/shore-excursions"`): `ports`, `operators`, `port_calls`, `excursions`, `departures`, `guests`, `bookings`, `incidents`, `claims`, `statements`, `clock`.

## Endpoints
58 total — 57 under `/shore-excursions` plus `POST /_clock/set_current_utc` (no auth headers). Verified programmatically against `SCAFFOLD.yaml`: the method+path sets match exactly in both directions, and all 14 serializer field tuples match the SCAFFOLD entity field lists (including `ExcursionDeparture`'s 24 fields, so `forgone_gross_ticket_cents` stays internal, and `GuestIncident` having no `resolution_note`).

## Notable design decisions
- **Global 47-rule precedence ladder wins wherever PRD prose disagrees**: DISPATCH checks `ERR_TIMING_RISK_RED` (36) before `ERR_NO_ELIGIBLE_TENDER_WAVE` (40); COMPLETE checks the `actual_return_utc` window (9) before departure state (17); statement ADJUST's `adjustment_cents` guard and the claim `settlement <= claimed` guard fire before their transition checks (21/20).
- **Segregation-of-duties and ownership guards read the raw body before shape validation** (`ERR_BOOKING_NOT_OWNED`, `ERR_SEGREGATION_OF_DUTIES`, `ERR_AUDITOR_CANNOT_APPROVE`), matching their high ladder priority.
- **No timers**: every clock-driven effect (cutoff closure, delay-driven RED cascade, band recompute) materialises lazily on read or write. Booking creation deliberately does *not* persist the SELLING→CLOSED cutoff flip; it raises `ERR_SALES_CUTOFF_PASSED` while GETs and departure/port-call writes do persist it.
- **Seat counts are derived** from the booking set on every recompute rather than incremented, so cancellations, no-shows and rebalances can't drift.
- Deterministic ordering via `(created_at, _seq)`; tender-wave selection resolves the winner before mutating any wave, so a failed selection leaves no partial state.
- Money strictly in integer cents/bps with half-up `Decimal`; commission rounds per line then sums, ticket price rounds per guest then multiplies.

## Verification
Two end-to-end smoke passes against a fresh boot: Pass A (ALONGSIDE) full vetting → publish → sell → check-in → dispatch → late COMPLETE with per-guest 10545 / quoted 42180 / fee 1265 / charge 43445, provisional commission 8436, guarantee breach → `return_guarantee_honored false` + `REFUNDED` + 42180 refund + 25000 repatriation, FINAL statement `claim_offset_cents` 20000, revenue report `net_line_revenue_cents` -23735. Pass B (TENDER) exercised `ERR_NO_ELIGIBLE_TENDER_WAVE`, `ERR_TENDER_WAVE_OVERLAP`, `ERR_MEETING_POINT_CONGESTED`, `ERR_ALLOCATION_MISMATCH`, `ERR_VOYAGE_MISMATCH`, `ERR_LANGUAGE_UNAVAILABLE`, `ERR_BOOKING_NOT_OWNED`, wave selection, allocation rebalance, operational cancellation cascade, guest cancel refund tier, and the 300-minute delay → RED → `SELLING → CLOSED` cascade.

Server was stopped afterwards, so port 10000 is free and `__pycache__` removed for a clean harness boot. `test_helpers/` and `test_suite/` were never read or written.

## Step 7: Run tests and iterate — 2026-09-01T17:52:00.000Z

Clean sweep: all 8 parallel rounds returned 142/142.

## Summary

**Iterations run:** 2 (iteration 1 sweep = 118–121/142 per round; iteration 2 sweep = 142/142 in all 8 rounds).

**Tests deleted:** none. Every failing test's asserted rule traced to a verbatim PRD sentence and was uniquely derivable — all 26 failures were test-artifact bugs, not PRD-silence.

**Fixes applied to `test_helpers/`:**
- `test_suite/conftest.py` — `api` fixture changed from `scope="session"` to function-scoped (and its `requests.Session` closed on teardown). Under `--isolation per-test-server` the harness restarts the server before every test, so a session-scoped client handed the next test a dead keep-alive socket; this was the sole cause of the 5 flaky `ConnectionResetError` / `RemoteDisconnected` failures that appeared in only some rounds (`test_the_return_guarantee_is_frozen_true_only_for_a_line_operated_departure`, `test_checking_in_forty_six_minutes_before_the_meeting_is_rejected`, `test_a_rebalance_that_breaks_both_allocation_rules_reports_the_partition_first`, `test_a_weather_cancellation_pays_no_goodwill_and_records_no_reliability_strike`, `test_a_meeting_time_before_the_ships_arrival_is_refused`).
- `test_helpers/assertions.py` → `assert_money_conservation` — the helper asserted `refunded + retained == charge_total` for every non-`AUTHORIZED` booking. PRD §3.7 pins `retained_cents` only twice: 0 while `AUTHORIZED`, and `charge_total_cents − refunded_cents` "once `financial_status` is terminal". `CHARGED` is explicitly non-terminal (§3.6 lists terminal as `REFUNDED`/`RETAINED`/`VOIDED`), and §3.7's void branch says `retained_cents` is "left at 0", contradicting the identity for `VOIDED`. The helper now checks only the refunded side in those two states. This was the one genuine assertion mis-translation (`test_two_bookings_pushed_down_opposite_money_paths_still_balance`).

**Fixes applied to `test_suite/` (22 sites across 6 files):** `get_success_data(validate_success(resp))` double-unwrap removed. `validate_success` already returns `body["data"]`, so passing its dict result into `get_success_data` raised `AttributeError: 'dict' object has no attribute 'status_code'` before any domain assertion ran. Rewritten to `validate_success(resp)`. 21 nested multi-line sites (`test_corner_calculations.py`, `test_corner_state_machines.py`, `test_corner_rbac_layers_and_consistency.py`, `test_difficulty_calculations.py`, `test_difficulty_state_machines_and_cascades.py`, `test_difficulty_dependencies_and_invariants.py`) plus 1 single-line site (`test_corner_rbac_layers_and_consistency.py:79`). This single upstream defect accounted for 20 of the 21 hard failures.

**Fixes applied to `implementation/`:** none. No implementation defect surfaced — every failure was in the test artifact, and no PRD-required check was weakened or removed.

Orchestrator verification: all 8 `workspace/implementation/results.{1..8}.json` report `passed=142 total=142 failed=0`.

## Step 8: Finalize PRD — 2026-09-01T18:00:00.000Z

`workspace/PRD_FINALIZED.md` created.

## Line counts
- `PRD.md`: 467 lines
- `PRD_FINALIZED.md`: 467 lines
- Delta: 0 lines (+0.0%); 1 sentence revised in place, 1 of 467 lines touched (0.2% of lines).

## Changes
- §3.7 (Cancellations, Refunds and Alternative Offers) — revise — `retained_cents` per `financial_status` is now enumerated by state instead of by "terminal / `AUTHORIZED`": it is `charge_total_cents − refunded_cents` while `PARTIALLY_REFUNDED`, `REFUNDED` or `RETAINED`, and 0 while `AUTHORIZED`, `CHARGED` or `VOIDED` — `implementation/services/ledger.py:47`, `:65`, `:94`, `:103`; `implementation/routes/bookings.py:146`, `:210`.

## Pre-edit search log

**Edit 1 — §3.7 `retained_cents`**

(a) Subject: the value of `booking.retained_cents` in every reachable `financial_status`, and every write site that can set it.

(b) Impl paths enumerated (grep `retained_cents` and `financial_status` across `implementation/`, then read each site and its callers):
- `routes/bookings.py:146` — creation seeds `retained_cents: 0` alongside `financial_status: "AUTHORIZED"`.
- `routes/bookings.py:203-210` — TICKET moves `AUTHORIZED → CHARGED` and does **not** touch `retained_cents`, so `CHARGED` carries 0. This is the path PRD.md was silent on.
- `services/ledger.py:36-48` `derive_financial_status` — sets `RETAINED` / `REFUNDED` / `PARTIALLY_REFUNDED` from the refund arithmetic and always writes `charge_total − refunded`. Callers: `guest_cancellation_settlement` (:78) and `line_cancellation_settlement` (:88).
- `services/ledger.py:62-65` `void_authorization` — `VOIDED` with `retained_cents = 0`, contradicting PRD.md's "terminal ⇒ `charge_total − refunded`". Callers: `cascades.close_departure_sales:69` (clock/RED/call-closure sales closure), `cascades.cancel_departure:140` (both WEATHER and OPERATIONAL branches), `cascades.cancel_booking_by_guest:226` (guest cancel from `BOOKED`). Verified every caller guards on `financial_status == "AUTHORIZED"` or `fulfillment_status == "BOOKED"`, so a `VOIDED` booking always has `refunded_cents == 0` — the "0" claim holds universally, not just at the Step 7 site.
- `services/ledger.py:91-94` `no_show_retention` — `RETAINED` with the full `charge_total_cents`. Callers: `cascades.mark_no_show:216` (explicit `MARK_NO_SHOW`, dispatch sweep at `:246`, port-call closure sweep at `:306`), all guarded on `financial_status == "CHARGED"` (hence `refunded_cents == 0`), so `charge_total` and `charge_total − refunded` agree — consistent with the new wording.
- `services/ledger.py:97-103` `return_guarantee_settlement` — `REFUNDED` with `charge_total − refunded`, i.e. the retained service fee. Caller `cascades.complete_departure:267`.
- `serializers.py:63` — field is exposed on every booking read, so the rule must hold in all states, including ones Step 7 never exercised.
- Cross-checked the three places PRD.md already pins the field (§3.6 no-show "full `charge_total_cents`", §3.7 guest-void "left at 0", §3.7 tiered guest cancellation "`charge_total_cents` less the new refunded total") — all three remain verbatim and are subsumed by, not contradicted by, the new sentence.

(c) Wording adjustment: dropped the "terminal" framing entirely rather than patching it, because `VOIDED` is terminal yet carries 0 while `PARTIALLY_REFUNDED` is non-terminal yet carries the difference — any terminal-based phrasing mis-describes at least one path. Enumerating the six statuses explicitly keeps the sentence true at every write site above. Added the trailing clause naming ticketing and the void explicitly so an implementer does not infer that capture writes a retention figure.

No other `<step_7_diff>` item produced a PRD edit: the `conftest.py` `api` fixture scope change and the 22 `get_success_data(validate_success(resp))` double-unwrap sites are test-artifact defects with no behavioral counterpart in `implementation/` (no impl fixes were applied and no tests were deleted, so there is no other candidate site of PRD-silence to pin).

## Step 9: Complete PRD — 2026-09-01T18:16:00.000Z

Done. All planned pins are applied and verified against the implementation.

**Files**
- Source: `workspace/PRD_FINALIZED.md` — 467 lines, 105,960 chars
- Output: `workspace/PRD_COMPLETED.md` — 467 lines, 113,325 chars
- Char delta: **+7,365**; line delta: **0** (every change is an in-paragraph insert or revision; no new sections, no new paragraphs)

**Counts:** 45 changes total — **36 ambiguity-pins**, **9 mismatch-revisions** (38 distinct paragraphs touched)

**Changes**

- §2.1 — revise — mismatch — `X-User-ID` rejection widened to "absent, empty or whitespace-only" — middleware.py:36
- §2.1 — insert — ambiguity — absent/unrecognised `X-User-Role` yields `ERR_UNAUTHORIZED`, never a shape error — middleware.py:38-40
- §2.2 — insert — ambiguity — `api_request_id` is the prefix plus twenty upper-case alphanumerics — response.py:15
- §2.3 — insert — ambiguity — query filters validated at priority 6 (enum outside set → `ERR_VALIDATION`; empty string treated as absent) — validation.py:146-153
- §2.3 — insert — ambiguity — equal `created_at` ties broken by insertion order, never by `id` — db.py:65-68
- §2.4 — insert — ambiguity — `created_at`/`updated_at` read from the logical clock; only `api_request_timestamp` is wall-clock; other instants render ms only when non-zero — db.py:49-63, util.py:40-55, serializers.py:90-99
- §2.5 — insert — ambiguity — `current_utc` mandatory; endpoint answers 200 with `data` of exactly `{"current_utc": …}` — routes/clock.py:12-19
- §2.5 — revise — mismatch — deferred closure materialises on reads/writes of the departure row only; port-call reads and writes never materialise it — routes/departures.py:117,133; services/cascades.py:326-337
- §2.7 — insert — ambiguity — the three `expected_*_version` fields are required non-negative integers, refused at priority 6 — routes/departures.py:41, routes/bookings.py:54, routes/statements.py:28
- §2.8 r10 — revise — ambiguity — `port_code` compared exactly, never case-folded; priority 6 already refused non-conforming codes — routes/ports.py:21,41-43
- §2.8 r20 — revise — ambiguity — TERMINATED-operator check binds only the `SUBMITTED → UNDER_OPERATOR_REVIEW` edge — routes/claims.py:93-95
- §3.1 — revise — ambiguity — `port_code` never normalised; lower-case is `ERR_VALIDATION` — routes/ports.py:21
- §3.1 — insert — ambiguity — `additional_delay_minutes` required non-negative int; `reason_code` accepted but never stored or exposed — routes/port_calls.py:36-39,147
- §3.1 — insert — ambiguity — delay recomputation bumps no departure `version` and never applies the 60-minute closure; RED-closed departures do bump — services/cascades.py:326-337
- §3.1 — revise — mismatch — wave overlap compares against every wave on the call (waves have no cancellable lifecycle) — routes/port_calls.py:159-167
- §3.2 — insert — ambiguity — `contact_email` any non-empty string; `insurance_expiry_date` is a full UTC instant compared as an instant — routes/operators.py:32-33,185
- §3.2 — insert — ambiguity — audit ordering's third tie-break is descending insertion order — services/safety.py:19
- §3.2 — insert — ambiguity — vetting-action rescore runs before the transition check and never itself auto-suspends — routes/operators.py:167; services/cascades.py:200-205
- §3.2 — revise — mismatch — auto-suspension fires only while `APPROVED`; strike trigger is "reaches or passes 3" — services/cascades.py:162-164
- §3.2 — revise — mismatch — suspension-cascade cancellations add no further `reliability_strikes` — services/cascades.py:194
- §3.3 — insert — ambiguity — a `duration_minutes` amendment bumps only the excursion's `version`, not the reprojected departures' — routes/excursions.py:148-150
- §3.3 — insert — ambiguity — publication's three checks are evaluated in ladder order (insurance runway reported before unapproved operator) — routes/excursions.py:174-181
- §3.3 — insert — ambiguity — a manager-requested withdrawal charges one strike per cancelled departure; only suspension-forced withdrawals do not — routes/excursions.py:204; services/cascades.py:175-180
- §3.4 — revise — ambiguity — slack is the minute count rounded half up *before* `risk_buffer_minutes` is subtracted; both figures are integers — services/timing.py:61-62
- §3.4 — revise — ambiguity — actual-basis slack uses the identical rounding order — services/timing.py:61-62
- §3.4 — insert — ambiguity — tender assignment takes no body fields and requires `SCHEDULED`/`SELLING`/`CLOSED` — routes/departures.py:175-180
- §3.4 — revise — mismatch — clock-driven closure evaluated on departure reads and departure writes only; not on bookings/fulfillment actions, not on any port-call read or write — routes/departures.py:117,133,150,177,199,235,258; routes/bookings.py:106
- §3.5 — insert — ambiguity — `birth_date` supplied/stored/echoed as a full UTC instant — routes/guests.py:23
- §3.5 — revise — ambiguity — rebalance requires `SCHEDULED`/`SELLING`/`CLOSED`, else `ERR_INVALID_DEPARTURE_STATE` — routes/departures.py:27,151-153
- §3.6 — revise — mismatch — dispatch checks `timing_risk_band_actual` before the tender-wave requirement — routes/departures.py:269-274
- §3.7 — insert — ambiguity — `refund_pct_bps` is 0 for `REPATRIATION_ALLOWANCE` and 1000 on `GOODWILL_CREDIT` — services/ledger.py:87,100
- §3.7 — insert — ambiguity — `reason_code` defaults to the entry's own `basis` when none supplied — services/ledger.py:26
- §3.7 — insert — ambiguity — wave release decrements by `total_capacity`/1 floored at 0, and the cancelled departure keeps its `tender_wave_id` — services/cascades.py:123-129
- §3.7 — revise — mismatch — goodwill goes to bookings found in `CHARGED` **or** `PARTIALLY_REFUNDED` — services/cascades.py:137-138
- §3.7 — insert — ambiguity — forgone gross defined as the exact sum of `quoted_total_cents` over the lines this cancellation itself moved to `CANCELLED_BY_LINE`, stored but not exposed — services/cascades.py:142,154; services/commission.py:88
- §3.7 — insert — ambiguity — alternative eligibility recomputes age at the candidate's `meeting_time_utc` and reuses the booking's stored language/medical acknowledgement — services/alternatives.py:36-38
- §3.8 — revise — mismatch — `resolution_note` accepted but neither stored nor exposed — routes/incidents.py:28-29,99
- §3.8 — insert — ambiguity — `settlement_amount_cents` may not be negative; exactly 0 is accepted — routes/claims.py:29
- §3.8 — insert — ambiguity — reserve release on `SETTLED` is floored at 0 — routes/statements.py:168-169
- §3.9 — revise — ambiguity — step five's forgone gross is the §3.7 definition, rounded half up per departure — services/commission.py:85-90
- §3.9 — insert — ambiguity — on ISSUE the closed-call requirement is reported before the open-claim block — routes/statements.py:133-139
- §3.9 — revise — ambiguity — `adjustment_cents` is mandatory on ADJUST; absence is `ERR_VALIDATION` — routes/statements.py:112-113
- §3.9 — revise — ambiguity — revenue report echoes `voyage_code` as null when unfiltered — services/revenue.py:51
- §3.9 — insert — ambiguity — statements in scope are those drafted against the scoped port calls regardless of operator — services/revenue.py:38-41
- §4 — insert — ambiguity — "Any" means all seven roles including `Guest`; only the clock endpoint needs no headers — middleware.py:17,30; routes/clock.py:15

Cross-checked with no change needed: §5 error→status table matches `errors.py` exactly; every endpoint path, verb and role list in §4 matches the blueprints and `endpoint(...)` decorators; the ladder positions for booking creation, departure creation and vetting actions already match impl check order.

---

## Pipeline complete

All 9 steps finished. Final state: 142 tests, 8/8 parallel stability rounds at 142/142; `workspace/PRD_COMPLETED.md` on disk.
