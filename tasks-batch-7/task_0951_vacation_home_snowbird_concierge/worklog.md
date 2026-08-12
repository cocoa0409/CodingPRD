# Worklog — task_0951_vacation_home_snowbird_concierge

Scenario (verbatim): `951. Vacation-Home & Snowbird Concierge: property-watch checklist & visit log, seasonal open/close & winterization, vendor management & work-order, rental-turnover linkage, mail/security & incident, key/access, subscription & per-visit billing, storm response`

Difficulty: **harder than Expert** (beyond-Expert band, per user request).

## Step 1: Create task directory — 2026-08-09T15:00:45.000Z

Created `tasks/task_0951_vacation_home_snowbird_concierge/` and `tasks/task_0951_vacation_home_snowbird_concierge/workspace/`. Host load at start: 1.31 / 8 cores, no foreign prd-bench runners.

## Step 2: Generate scaffold — 2026-08-09T16:23:40.000Z

Scaffold complete for task 0951.

## Files

| Path | Lines |
|---|---|
| `/home/ubuntu/github/CodingPRD/tasks/task_0951_vacation_home_snowbird_concierge/SCAFFOLD.yaml` | 6,301 |
| `/home/ubuntu/github/CodingPRD/tasks/task_0951_vacation_home_snowbird_concierge/SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 1,973 |
| `/home/ubuntu/github/CodingPRD/tasks/task_0951_vacation_home_snowbird_concierge/SCAFFOLD_CORNER_DESIGN.yaml` | 6,697 |

## Realised density (target → actual)

| Axis | Target | Actual |
|---|---|---|
| Entities | 19–22 | **23** |
| Endpoints | 100–120 | **142** |
| State machines | 14–17 (≥6 non-linear) | **18, of which 17 non-linear** (cyclic/parallel/branching) |
| Calculations | 38–48 (≥8 dual-variant) | **53, 10 dual-variant** |
| Validations / ladder rungs | 65–80 / 55–70 | **73 rows over 68 rungs**, one ladder |
| Error codes | 80–95 | **98** |
| Roles | 6–8 | **8** (segregation_of_duties model) |
| Cascade depth | ≥7 | **8** (Visit→Finding→WorkOrder→VendorAssignment→KeyIssuance→AccessGrant→KeyAsset rotation→prior grant INVALIDATED) |
| Conservation invariants | ≥8 | **11** |
| OCC rules | ≥2 | **3** (Finding, Subscription, KeyAsset) |
| Global constants | ≥40 | **105** |
| `gate_precedence` | 8–10 gates, every endpoint | **10 gates, 142/142 endpoints declare a subsequence** |
| §1.8 instances | ≥18 | **26** (9 rules × 2–3) |

Two-pipeline device implemented: Pipeline R (subscription watch) and Pipeline S (storm response) share one 68-rung ladder but diverge on approval order (Owner ceiling vs. StormCoordinator emergency ceiling, Owner rung never consulted), deadline arithmetic (landfall−lead vs. all-clear+SLA), surcharge tiers, entitlement applicability, and key-custody prerequisites.

## Self-checks

**A. Incremental writes** — built from 13 bounded part files, concatenated; no oversized single write.

**B. Lint** — `python3 -c "import yaml,sys; [yaml.safe_load(open(p)) for p in sys.argv[1:]]; print('YAML OK')"` → `YAML OK`. Two YAML classes of offender were hit and fixed: `$.data[0].id` inside flow mappings, and `grounds:` flow sequences containing `{id}` / `validations[priority=N]`. `scaffold_lint.py` verdict, verbatim:

```
Coverage
  §1.5 endpoints declared:    142
  §1.1 entities declared:     23
  §1.8 instances scanned:     26
  §1.9 instances scanned:     137
  Calls scanned (§1.8+§1.9):  1650

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

**C. Constant audit** — 105 declared constants; 289 distinct ALL_CAPS-with-underscore tokens in SCAFFOLD.yaml; **2 residuals**, both non-constants (`ALL_CAPS` in a comment, `ERR_XXX` in the fixed §1.0 envelope). **Zero** constant-shaped residuals (`*_THRESHOLD|_WINDOW_DAYS|_BUFFER_MINUTES|_CEILING|_RATE|_TIER|_CENTS|_PCT|_HOURS|_DAYS|_CAP`). The rest are enum members, state names, error ids, gate ids, or variant names.

**D. §1.9 breadth** — 137 non-stub + 11 stubs:

| section | non-stub | stubs |
|---|---|---|
| entities | 18 | 0 |
| state_machines | 14 | 0 |
| calculations | 14 | 0 |
| validations | 5 | 2 |
| endpoints | 6 | 0 |
| errors | 62 | 9 |
| rbac | 7 | 0 |
| cross_cutting_complexity_layers | 7 | 0 |
| consistency_model | 4 | 0 |

Error-code coverage **92/98 = 93.9 %**. Instance names unique across both design files; all 11 stubs cite a `difficulty_instance` that exists in `SCAFFOLD_DIFFICULTY_DESIGN.yaml`. No forbidden concurrency vocabulary anywhere.

## Reachability dead-ends found while writing (free downstream intelligence)

The 6 uncovered error codes are exactly the dead-ends — each is declared but no §1.5 chain can reach it:

1. **`ERR_STORM_NOT_ALL_CLEAR` (rung 28) — found and REPAIRED.** `ASSESSMENT_DUE` was only reachable *via* all-clear, so the rung could never fire. Repaired by adding a `StormEvent ALL_CLEAR → LANDFALL` secondary-landfall transition (also a second bidirectional pair). Now covered.
2. **`ERR_ACCESS_GRANT_INVALID` (rung 52, rotation half)** — rotation *eagerly* invalidates every stale grant, so a grant with a stale `rotation_index_at_grant` is already `INVALIDATED` and rung 19 (`ERR_ALREADY_TERMINAL`) fires first. Left as-is; the §1.9 instance asserts the reachable outcome.
3. **`ERR_VISIT_NOT_ARRIVED` (rung 20)** — `IN_PROGRESS` is only reachable through `arrive`, which requires `departed_at`, so `arrived_at` is never null at complete. Rung 18 pre-empts it.
4. **`ERR_VENDOR_NOT_EMERGENCY_CAPABLE` (rung 46)** — `vendor_selection` filters non-emergency vendors out of the candidate set, so the empty pool yields `ERR_NO_ELIGIBLE_VENDOR` (rung 47) instead. Classic selector-pre-filter-kills-its-own-recheck.
5. **`ERR_ENTITLEMENT_EXHAUSTED`** — no endpoint *requires* a unit; consumption is silent and falls through to the OVERAGE branch.
6. **`ERR_VISIT_TYPE_NOT_COVERED`** — an uncovered visit type is simply billed as overage, never rejected.
7. **`ERR_PROPERTY_HAS_OPEN_STORM_HOLD`** — declared in §1.6 but no rung in the 68-rung ladder references it.

Also fixed mid-flight: `Finding.visit_id` was required, but `declare-lost` synthesizes a Finding on properties that may have no COMPLETED Visit — made nullable with the null case pinned. And `access_grant_capacity` originally counted the candidate grant against itself; now excludes it explicitly.

**Orchestrator verification:** all three files `yaml.safe_load` clean independently; surface confirmed on disk = 23 entities / 18 SMs / 53 calcs / 73 validations / 142 endpoints / 98 errors / 8 roles. Largest surface generated to date (prior max 121 endpoints at 0948).

## Step 3: Copy INSTRUCTION.md — 2026-08-09T16:25:10.000Z

Copied `./INSTRUCTION.md` → `tasks/task_0951_vacation_home_snowbird_concierge/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-08-09T16:45:00.000Z

PRD generated at `/home/ubuntu/github/CodingPRD/tasks/task_0951_vacation_home_snowbird_concierge/workspace/PRD.md`.

## Output

**978 lines**, ending at §5 with no audit footer. Written in 8 bounded appends (no single giant write).

### Section outline
- **§1 Introduction** (3 paragraphs: domain pain, the two-pipelines-one-ladder framing with all five divergences, money/pinned-order framing)
- **§2 Global Specifications** — 2.1 Operators, Roles and Identity Binding · 2.2 API Response Structure (verbatim, byte-identical — verified) · 2.3 Pagination, Sort Order and Collection Filters · 2.4 Common Resource Properties and the Version Counter · 2.5 The Logical Clock · 2.6 Money, Rounding and Derived Precision · 2.7 The Write-Gate Ladder and the Per-Endpoint Gate Subsequence · 2.8 The Numbered Validation Ladder · 2.9 Un-numbered Gates · 2.10 Optimistic Concurrency Control · 2.11 Conservation Invariants · 2.12 Two Pipelines Through One Ladder · 2.13 Open Friction Points
- **§3 Business Logic** — 3.1 Homeowners, Homes and the Two Independent Property Axes · 3.2 Plans, Subscriptions, Billing Cycles and the Entitlement Ledger · 3.3 Absence Windows, Checklist Templates and Scheduling a Visit · 3.4 Executing a Visit, and the Cascade that Completion Fires · 3.5 Findings, Triage and the Work-Order Cost Chain · 3.6 Vendors · 3.7 Keys, Lockbox Codes and Access Custody · 3.8 Seasonal Close, Winterization and Spring Open · 3.9 Rental Turnovers, Mail Holds and Security Incidents · 3.10 Storm Response · 3.11 Invoicing, Tax, Payment and Delinquency
- **§4** 142-row endpoint table (4 columns) · **§5** 98-row error table (2 columns)

### Per-axis coverage
| Axis | Scaffold | Rendered |
|---|---|---|
| Entities / fields | 23 / 225 | 225 field names in backticks, **all also in non-table narrative** |
| State machines / transitions | 18 / 120 | all 120 from→to pairs, preconditions, side effects |
| Calculations | 53 (10 with variants) | all 53, every variant discriminator + worked examples + pinned orders |
| Validations / rungs | 73 rows / 68 rungs | all 73 as ordered prose in §2.8, each with error id, status, applies_to scope |
| Un-numbered gates | 28 | all, banded, in §2.9 |
| Endpoints | 142 | §4 table (4 cols) + §2.7 table giving gate subsequence, success status, request/query fields |
| Errors | 98 | all in §5 table; **98/98 also named in §2/§3 prose with trigger** |
| Roles | 8 | all named, all `identity:` translated (2 entity-backed, 6 opaque) |
| Global constants | 105 | all values recoverable (3 percentages rendered as "18/5/3 percent") |
| Gates | 10 | full total order + per-endpoint subsequence for all 142 |
| Conservation invariants | 11 | all 11 in §2.11 |
| OCC rules | 3 | write_endpoint + `expected_<parent>_version` + error_id + 412 + **count pinned** ("one increment per mutated row per request") + post-mutation response value |

### Hard contracts
```
Field coverage check:
- entities[].fields: 225 required, 225 present, 0 missing
- endpoints[].request_body: 108 required, 108 present, 0 missing
- endpoints[].query_params: 36 required, 36 present, 0 missing
Status: PASS

Rule coverage check:
- validations[] with priority: 73 checked, 73 expressed, 0 missing
- concurrency_rules[] OCC rejections: 3 checked, 3 expressed, 0 missing
- state_machines[].transitions: 120 checked, 120 fully expressed, 0 missing
- calculations[]: 53 checked, 53 fully expressed, 0 missing
- validations[] conditions: 73 checked, 73 matchable to error_id, 0 missing
- endpoints[].side_effects / applies_to: 142 checked, 142 expressed, 0 missing
- entities[].fields[] structured content: 225 checked, 225 reconstructible, 0 missing
- sibling-branch symmetry: 11 groups checked, 11 equal density, 0 asymmetric
Status: PASS

Path purity check (§3 only):
- backtick tokens scanned: 1591
- tokens starting with `/`: 0 | bare HTTP-method tokens: 0 | method+path tokens: 0
Status: PASS
```
§2.2 verified byte-identical to `section-2.2-response-structure.md`.

### Friction points carried forward un-prejudged (13, §2.13)
1. **F1** — `expected_storm_response_version` is a required input with a G4 gate but **no error_id exists** for its rejection (only 3 OCC codes declared; none for StormResponse).
2. **F2** — conservation invariants assert `VISIT_OVERAGE`, `GUARANTEE_CREDIT` and `ENTITLEMENT_OFFSET` lines that **no declared side effect creates** (the 4 that *are* auto-appended are enumerated).
3. **F3** — rekey-pending refusal: rung 50's `ERR_KEY_COPIES_UNAVAILABLE` vs the standalone `ERR_KEY_REKEY_PENDING`.
4. **F4** — out-of-window grant: rung 52's `ERR_ACCESS_GRANT_INVALID` vs `ERR_GRANT_WINDOW_NOT_OPEN`.
5. **F5** — dispatch from `PENDING_APPROVAL`: rung 18's `ERR_INVALID_STATE_TRANSITION` vs `ERR_APPROVAL_REQUIRED`.
6. **F6** — issuing on a cancelled subscription: rung 58's `ERR_INVOICE_HAS_NO_LINES` vs `ERR_SUBSCRIPTION_CANCELLED`.
7. **F7** — reinstatement credential failures: rungs 44/45 scope themselves to dispatch+accept, but the catalogue conditions are endpoint-agnostic.
8. **F8** — `MAIL_DISPOSITION` line appended on the `ACTIVE`→`FORWARDED` edge but not on `OVERFLOW`→`FORWARDED` (sibling asymmetry).
9. **F9** — `ERR_VISIT_TYPE_NOT_COVERED` and `ERR_ENTITLEMENT_EXHAUSTED` have no derivable trigger (entitlement always falls through to overage).
10. **F10** — `Owner.status` `INACTIVE` is unreachable; nothing writes it.
11. **F11** — a freshly registered property: declared defaults 0.0/`NORMAL` vs the derivation the registration is declared to run, which yields 40.0/`ELEVATED`.
12. **F12** — whether a **routine** dispatch with no eligible key is refused: the pipeline narrative says Pipeline R may not, the key-selection rule has no pipeline condition and says dispatch succeeds; no error code names the condition.
13. **F13** — intra-band ordering of un-numbered gates against numbered rungs of the same band.

Two summary-vs-detail drifts were caught and repaired during the final sweep: the §1 and §2.12 statements of the fifth pipeline divergence originally asserted a key-custody mechanism the rules do not implement — both now point at F12 instead of asserting it.

## Step 5: Generate unit tests — 2026-08-09T17:30:00.000Z

Test infrastructure and suite are complete and verified.

## Files written

**`test_helpers/`** (2 283 lines)

| file | lines | contents |
|---|---|---|
| `__init__.py` | 29 | barrel export (framework + PRD-specific) |
| `types.py` | 714 | 40 status/role enums + 23 entity TypedDicts (every entity carries `updated_at`+`version`) |
| `api_client.py` | 438 | **142 endpoint methods**, one per PRD endpoint |
| `api_errors.py` | 211 | **98 error ids** + HTTP status map, registered via `set_error_http_status_map` |
| `assertions.py` | 393 | `assert_same_instant` / `parse_instant` (semantic ISO-8601 comparison), per-entity assertions, all 11 conservation-invariant checkers |
| `factories.py` | 213 | payload factories, input fields only, unique owner emails |
| `constants.py` | 180 | every threshold named in the PRD |
| `test_users.py` | 83 | 8 role headers + `make_owner_headers` / `make_vendor_headers` per-instance builders, `TECH_ALPHA_ID`/`TECH_BRAVO_ID` |
| `fixtures.py` | 735 | 5 tiers: subscribed property -> completed visit -> triaged finding -> work order -> dispatch/assignment/completion; storm-to-ASSESSMENT_DUE; winterized property; draft/issued invoice; key & grant helpers |

**`test_suite/`** (5 926 lines): `conftest.py` + 12 domain-named files.

## Coverage

- **182 tests** collected. Queue A = **52**, Queue B = **130**.
- **26/26 §1.8 difficulty instances** covered, every one by **>=2 tests**.
- **130/137 non-stub §1.9 corner instances** covered; 7 skipped (register below). All 11 `excluded_because:` stubs verified as resolving to real difficulty instances and not translated.
- A verification pass confirms: every test has exactly one trailing `Design:` line resolving to a real instance; every docstring quote of >=8 words survives a whitespace-normalised literal grep of `PRD.md`; no `skip`/`skipif`/`xfail`; no "scaffold"/§ leakage into generated code.

## SKIPPED-INSTANCE REGISTER (7)

1. **`Corner/calculations/visit_duration_minutes_floors_the_arrival_to_completion_gap`** — *not uniquely derivable*. PRD 3.4 states "A read of a completed visit also exposes a duration in whole minutes, the floor of the seconds between `arrived_at` and `completed_at` divided by sixty" but **never names the response field**, and no Visit field for it is declared anywhere in the PRD. Two readers would ship `duration_minutes` vs `visit_duration_minutes` vs an omitted field.
2. **`Corner/errors/err_approval_required_when_dispatching_a_pending_work_order_returns_409`** — **friction F5**. "*Determined:* the dispatch is refused with HTTP 409. *Not determined:* which of the two identifiers" (`ERR_APPROVAL_REQUIRED` vs `ERR_INVALID_STATE_TRANSITION`).
3. **`Corner/errors/err_grant_window_not_open_before_start_returns_409`** — **friction F4**. "*Not determined:* which identifier the out-of-window case carries" (`ERR_ACCESS_GRANT_INVALID` vs `ERR_GRANT_WINDOW_NOT_OPEN`).
4. **`Corner/errors/err_key_rekey_pending_blocks_issuance_after_declare_lost_returns_409`** — **friction F3**. "*Not determined:* which of the two identifiers it carries" (`ERR_KEY_COPIES_UNAVAILABLE` vs `ERR_KEY_REKEY_PENDING`). Collateral loss: the declare-lost -> rekey cascade (rekey WO of 48970, synthesized `visit_id`-null SECURITY finding, `copies_lost` ledger) is now untested.
5. **`Corner/errors/err_subscription_cancelled_blocks_invoice_issue_returns_409`** — **friction F6**. "*Not determined:* which identifier" (`ERR_SUBSCRIPTION_CANCELLED` vs `ERR_INVOICE_HAS_NO_LINES`).
6. **`Corner/errors/err_vendor_coi_expired_on_reinstate_returns_409`** — **friction F7**. "*Not determined:* whether an expired certificate or licence at reinstatement answers `ERR_VENDOR_COI_EXPIRED`... rungs 44 and 45 scope themselves to dispatch and acceptance only."
7. **`Corner/errors/err_vendor_license_expired_on_reinstate_returns_409`** — **friction F7**, same clause. (F7's *determined* half, `ERR_VENDOR_RATING_BELOW_FLOOR`, **is** tested.)

## NEAR-MISS REGISTER (13)

**A. Error-precedence pairs resolved with `validate_error_is_one_of` (rungs 18/19 both fire; not an F1–F13 friction, so the skill's `error-precedence` silence pattern applies). Each also asserts the HTTP status explicitly.**

1. `Corner/state_machines/cancelled_subscription_is_terminal_and_rejects_pause` — instance asserts `ERR_ALREADY_TERMINAL`; test accepts `{ERR_ALREADY_TERMINAL, ERR_INVALID_STATE_TRANSITION}`. Rung 18 ("current status is a declared source state") fires on any terminal state before rung 19 ever runs, making rung 19 dead under a strict reading. *Distance from the edge: zero — the state and side effects (cycle CLOSED, carry-out 0, expired 3) are still pinned exactly.*
2. `Corner/errors/explicit_rotation_invalidates_the_earlier_grant_and_activation_returns_409` — same pair. Every other assertion (rotation index 1, `code_snapshot` 9001, count 2, INVALIDATED/CODE_ROTATION, `active_grant_count` 0) is exact.
3. `Corner/errors/err_line_already_void_on_second_void_returns_409` — accepts `{ERR_LINE_ALREADY_VOID, ERR_INVALID_STATE_TRANSITION, ERR_ALREADY_TERMINAL}`; F13 makes the un-numbered G5 gate's position against rungs 18/19 of its own band undetermined.
4. `Corner/errors/err_invoice_already_paid_on_void_returns_409` — accepts the same three. Rung 30 is numbered but sits *after* 18/19 in G5, and `PAID` is not a declared source state for void, so rung 30 may be unreachable by construction. **This is the strongest hypothesis in the register: rung 30's invoice arm may be dead.**
5. `Corner/errors/err_turnover_stage_invalid_when_skipping_cleaning_returns_409` — accepts `{ERR_TURNOVER_STAGE_INVALID, ERR_INVALID_STATE_TRANSITION}`; CHECKOUT->READY is simultaneously "not the declared successor" and "not a declared transition".
6. `Corner/errors/err_finding_has_live_work_order_on_dismiss_returns_409` — accepts `{ERR_FINDING_HAS_LIVE_WORK_ORDER, ERR_INVALID_STATE_TRANSITION}`. **Reachability finding:** rung 23 appears unreachable cleanly — a finding can only hold a live work order while it is `WORK_ORDERED`, which is not a declared source state for dismiss, so rung 18 pre-empts rung 23 on every path.

**B. Assertions dropped from an otherwise-kept instance**

7. `Corner/state_machines/finding_monitor_rejected_for_high_severity` — the recipe's `escalation_score == 40.0` assertion was **dropped**. It depends on the posture term of a freshly registered property, which **friction F11** leaves undetermined (0.0/`NORMAL` vs 40.0/`ELEVATED` -> score 30.0 vs 40.0). The rejection and the `TRIAGED` status are asserted exactly.
8. `Difficulty/transitive_cascade/storm_assess_completion_depth_eight_cascade_to_grant_invalidation` — `total_cents` on the auto-dispatched storm work order is **not asserted** (labour 17000 / parts 25000 / markup 7560 are). Dispatch freezes `surcharge_pct_applied` at 0.35 but the PRD declares no cost-chain re-run at dispatch, so the total is 49560 or 66906 depending on the reading. *This is a genuine PRD gap worth adjudicating downstream.*

**C. Input deviations from the instance's stated setup**

9. `Difficulty/resource_temporal_overlap/vendor_assignment_closed_interval_exclusive_occupancy_conflict` — the recipe specifies "The property has no KeyAsset, so both assignments are stamped `access_blocked_flag` true". That is precisely **friction F12** (whether a routine dispatch with no eligible key succeeds). The fixture **registers a 4-copy PHYSICAL key** so the dispatch is unambiguous, and the `access_blocked_flag == true` assertion is dropped. The window-conflict claim itself is untouched.
10. Every fixture that dispatches (`setup_dispatched_work_order`, and tests 55/59/61/124/126/30) **registers a key asset by default** for the same F12 reason, deviating from several recipes that dispatch against key-less properties.
11. `Corner/validations/seasonal_gate_precedes_occupancy_gate_on_visit_create` — the recipe's setup (occupancy -> `RENTAL_OCCUPIED`, then `BEGIN_CLOSE`) is **unbuildable**: `BEGIN_CLOSE` requires `occupancy_state` VACANT and `RENTAL_OCCUPIED` requires `seasonal_state` exactly OPEN. The fixture **interleaves instead**: `BEGIN_CLOSE` while VACANT, then drives a turnover to `CHECKIN`, whose own side effect flips occupancy to `RENTAL_OCCUPIED` with no seasonal precondition. The asserted outcome (`ERR_SEASONAL_STATE_FORBIDS_VISIT` with both rungs violated) is unchanged.
12. Alarm-class incidents (instances 27, 37, 83, 130) — investigation forces an `ALARM_RESPONSE` visit, whose scheduling needs an active subscription and whose window the PRD does not default. The fixtures **add a subscription and supply `checklist_template_id` + window** on every alarm-class `investigate`, deviating from recipes that investigate on unsubscribed properties.
13. `Difficulty/boundary_precision_check/interior_temperature_exactly_at_trip_point_raises_no_incident`, second test — uses **51.0 °F rather than the recipe's 51.9** for the "just below the trip point" side, because 55 - 51.9 is not exact in binary and the score assertion would ride on the implementer's rounding substrate. *Distance from the edge: 1.0 °F below a 52.0 trip point instead of 0.1 °F. The strict `<` comparison is still exercised; the exact-boundary side (52.0) is pinned precisely.*

**Also worth flagging as an unverified fixture dependency (affects tests 42, 56, 125):** the PRD never specifies the **window of the access grant created by the dispatch chain**. Three tests reach `start-work`, which requires the logical clock inside that grant's window; they assume it mirrors the assignment window. If an implementer derives it otherwise, those three fail in setup, not in their assertion.

**Orchestrator verification:** 182 `def test_` across 12 files; 182 `Design:` tags (52 Difficulty + 130 Corner); zero `skip`/`skipif`/`xfail`.

## Step 6: Generate implementation — 2026-08-09T17:30:00.000Z

Implementation complete. All checks pass.

## Module list (line counts)

| Module | Lines | Role |
|---|---|---|
| `core.py` | 452 | constants, enums, terminal-state table, error catalogue + HTTP map, strict ISO parser / canonical renderer, `Decimal` half-away-from-zero rounding, in-memory store, `touch()` version discipline, response envelope |
| `gates.py` | 328 | G1 auth, G2 role/scope, G3 existence, G5 `check_state`, G10 payload (rungs 59–62/64), pagination + filters |
| `calc.py` | 657 | all 53 calculations + derived-field re-derivations + invoice pipeline |
| `serialize.py` | 415 | 23 entity serialisers (every datetime through `fmt_iso`) |
| `ops.py` | 293 | cross-module operations (visit/finding/work-order creation, submit + auto-approve, dispatch + key chain, cycle close, sweep settlement, occupancy flips) |
| `app.py` | 84 | blueprint registration, error handlers, bounded-retry bind |
| `routes/system.py` | 25 | logical clock |
| `routes/owners.py` | 80 | owners |
| `routes/properties.py` | 248 | properties, seasonal axis, occupancy axis, risk-posture |
| `routes/plans.py` | 63 | service plans |
| `routes/subscriptions.py` | 339 | subscriptions + billing cycles |
| `routes/catalog.py` | 130 | away periods + checklist templates |
| `routes/visits.py` | 355 | visits + the completion cascade |
| `routes/findings.py` | 86 | findings |
| `routes/vendors.py` | 126 | vendors |
| `routes/workorders.py` | 378 | work orders + vendor assignments |
| `routes/keys.py` | 277 | key assets, issuances, access grants |
| `routes/facilities.py` | 406 | winterization, turnovers, mail holds |
| `routes/incidents.py` | 149 | security incidents |
| `routes/storms.py` | 280 | storm events + responses |
| `routes/invoices.py` | 214 | invoices + lines |
| `start.sh` / `requirements.txt` | 8 / 1 | guarded launcher, Flask only |

Total 5,394 lines.

## Route diff (verbatim, `(METHOD, path)` pairs with parameter names normalised to `{}`)

```
SCAFFOLD endpoints (method, normalised path) : 142
FLASK url_map (method, normalised path)      : 142
MISSING (0):
EXTRA (0):
```

## Adjudication A — timestamp rendering (three cases) and parsing strictness

**Rendering — one uniform rule, `%Y-%m-%dT%H:%M:%S.mmmZ` (exactly three fractional digits, literal `Z`), applied through the single helper `core.fmt_iso`, which every datetime field in `serialize.py` passes through.**

1. **Server-generated stamps** (`created_at`, `updated_at`, `departed_at`, `arrived_at`, `completed_at`, `triaged_at`, `dismissed_at`, `issued_at`, `paid_at`, `reported_at`, `offered_at`, `accepted_at`, `finished_at`, `closed_at`, `paused_at`, `resumed_at`, `cancelled_at`, `delinquent_since`, `secured_at`, `assessed_at`, `landfall_recorded_at`, `all_clear_at`, `last_temp_reading_at`, `last_eligibility_evaluated_at`, `issued_at` on issuances): the logical-clock instant rendered in that form. Grounded in §2.4 ("`created_at` ... ISO 8601 UTC with three fractional digits ... `updated_at`, in the same format").
2. **Caller-supplied instants echoed back** (`started_on`, `period_start`, `scheduled_start_at/_end_at`, `start_at/end_at`, `start_on/end_on`, `checkout_at/checkin_at`, `coi_expires_at`, `license_expires_at`, `landfall_eta_at`, `window_start_at/_end_at`): parsed to an aware UTC datetime and **re-rendered canonically**, so `"2026-05-01T00:00:00Z"` reads back as `"2026-05-01T00:00:00.000Z"` and `"...+02:00"` reads back normalised to UTC. Rationale: the PRD states one instant format and states it as a property of the system's timestamps, not of a subset; a mixed echo/canonical scheme is the only reading under which two fields of the same resource can disagree in format.
3. **Values derived from caller input** (`period_end`, `return_deadline_at`, `secure_sweep_deadline_at`, `assessment_deadline_at`, `end_on` after an extension): computed on the parsed aware datetimes and rendered identically.

`api_request_timestamp` in `meta` is real wall-clock UTC in the same three-digit form (§2.2 calls it server-generated, and §2.5's logical clock governs "deadline, expiry, window and age comparison", not the envelope).

**Parsing strictness.** `core.parse_iso` requires the `T` separator **and** an explicit zone designator (`Z`/`z`, `±HH:MM`, `±HHMM`); 0–6 fractional digits are accepted. A space separator, a bare date (`2026-05-01`), and a zone-less datetime (`2026-05-01T00:00:00`) are all **rejected**, and the rejection is routed to `ERR_INVALID_FIELD_TYPE` (rung 60) because no code in the catalogue names malformed-instant.

## Adjudication B — enum / value error routing (exhaustive closed lists)

**`ERR_INVALID_ENUM_VALUE` (rung 61)** routes **exactly and only** these request fields, per the PRD's own closed list: `visit_type`, `trigger_source`, `defer_reason`, `severity`, `category`, `incident_type`, `key_type`, `line_type`, `tier`, `entitlement_rollover_policy`, `billing_mode`, `trade`, `work_type`, `damage_level`, `reopen_reason`, `notification_preference`, `to_state`, `action`, `revoke_reason`, and `to_status` (members taken per endpoint: `RentalTurnover.status` on turnover advance, `StormEvent.status` on storm advisory). **No other field routes here.** Named exclusions and where they go instead:

- `step_code` — *is* on the PRD's rung-61 list but §3.8 gives it a dedicated code in its own sentence ("Anything else ... is rejected with `ERR_WINTERIZATION_STEP_INVALID`"). §3 detail wins: unknown `step_code` -> `ERR_WINTERIZATION_STEP_INVALID` (400). Rung 61 is therefore never reached for `step_code`.
- `disposition` — on the rung-61 list but no endpoint anywhere accepts a `disposition` field; unreachable.
- `status` (service-plan publication, checklist-template publication), `default_finding_category`, `covered_visit_types` members, `taxable`, `emergency_capable`, `snowbird_flag`, `storm_guarantee_included` — **not** on the list. `default_finding_category` is validated against `CATEGORIES` via an explicit per-endpoint override (it is the `category` enum under another name); `covered_visit_types` membership is enforced at rung 68 -> `ERR_UNIQUENESS_VIOLATION`; `status` is accepted as supplied (no rung rejects it — recorded as a resolution).

**Every other value-shaped rejection**, exhaustively:
- Missing declared-required field -> `ERR_MISSING_REQUIRED_FIELD` (rung 59), any endpoint.
- Wrong JSON type, including an unparseable instant string and a wrong-typed foreign key -> `ERR_INVALID_FIELD_TYPE` (rung 60), any endpoint.
- Numeric out of range -> `ERR_VALUE_OUT_OF_RANGE` (rung 62), for exactly: `travel_distance_miles`, `freeze_setpoint_f`, `rating`, `cadence_days`, `copies_total`, `copies_issued`, `hourly_rate_cents`, `monthly_fee_cents`, `included_visit_units`, `estimated_labour_hours`, `estimated_parts_cents`, plus `approval_ceiling_override_cents` (§3.1 "must be zero or greater"; the only numeric-range code available). No other numeric field is range-checked — notably `amount_cents`, `package_delta`, `thermostat_f`, `actual_labour_hours`, `actual_parts_cents`, `interior_temp_f`.
- Checklist arrays -> `ERR_CHECKLIST_MISMATCH` (rung 63), visit completion only.
- Interval end <= start -> `ERR_INTERVAL_MALFORMED` (rung 64), for exactly the five declared pairs.
- Owner email non-unique **or** missing `@`, and `covered_visit_types` empty/out-of-set -> `ERR_UNIQUENESS_VIOLATION` (rung 68).
- Line sign -> `ERR_LINE_SIGN_INVALID`; winterization step membership / missing `thermostat_f` -> `ERR_WINTERIZATION_STEP_INVALID`; `ALL_REQUIRED` with `thermostat_f` < 50 -> `ERR_THERMOSTAT_BELOW_MINIMUM`.

## F1–F13 adjudication table

| # | Reading implemented | PRD sentence leaned on | The alternative would have |
|---|---|---|---|
| **F1** storm-response OCC code | Minted `ERR_STALE_STORM_RESPONSE_VERSION`, **HTTP 412**, raised inside G4 before any target-state rung | F1: "*a mismatch ... must reject the request inside the concurrency band, before any target-state rung is evaluated ... the other three concurrency rejections all answer HTTP 412*" | reused one of the three declared stale codes (semantically wrong parent) or answered 409 via a state code |
| **F2** invariant-required lines | **No automatic append.** `VISIT_OVERAGE`, `GUARANTEE_CREDIT` and `ENTITLEMENT_OFFSET` lines are appended only by the operator through `POST /invoices/{id}/lines`. `billable_amount_cents` and `guarantee_credit_cents` are computed and stored | F2: "*No visit transition, no storm-response transition and no entitlement rule declares an invoice-line side effect for `VISIT_OVERAGE`, `GUARANTEE_CREDIT` or `ENTITLEMENT_OFFSET`*"; the enumerated auto-appending types are `SUBSCRIPTION_FEE`, `WORK_ORDER`, `FALSE_ALARM_FEE`, `MAIL_DISPOSITION` only | auto-appended three line types no declared side effect authorises, changing every invoice total |
| **F3** rekey vs copies | Split, **rekey checked first**: `rekey_pending_flag` true -> `ERR_KEY_REKEY_PENDING`; insufficient copies -> `ERR_KEY_COPIES_UNAVAILABLE` | §2.9: "`ERR_KEY_REKEY_PENDING` when an issuance is requested on a key with `rekey_pending_flag` true" — a dedicated code whose condition is exactly this | folded both into `ERR_KEY_COPIES_UNAVAILABLE` per rung 50, leaving `ERR_KEY_REKEY_PENDING` dead |
| **F4** grant validity vs window | Split: stale `rotation_index_at_grant` -> `ERR_ACCESS_GRANT_INVALID`; clock outside the closed window -> `ERR_GRANT_WINDOW_NOT_OPEN`. On `start-work`, *no* PENDING/ACTIVE grant at all -> `ERR_ACCESS_GRANT_INVALID`; grants exist but none is in-window -> `ERR_GRANT_WINDOW_NOT_OPEN` | §2.9: "`ERR_GRANT_WINDOW_NOT_OPEN` when the logical clock lies outside the grant's closed window" | folded both into `ERR_ACCESS_GRANT_INVALID` per rung 52, leaving `ERR_GRANT_WINDOW_NOT_OPEN` dead |
| **F5** dispatch from `PENDING_APPROVAL` | **`ERR_APPROVAL_REQUIRED`** (409) | §2.9: "`ERR_APPROVAL_REQUIRED` when a work order is dispatched while still `PENDING_APPROVAL`" — the code exists for exactly this state | returned `ERR_INVALID_STATE_TRANSITION` per rung 18, leaving `ERR_APPROVAL_REQUIRED` dead |
| **F6** issuing on a cancelled subscription | Split across gates: cancelled subscription -> `ERR_SUBSCRIPTION_CANCELLED` in **G5**; no ACTIVE line -> `ERR_INVOICE_HAS_NO_LINES` in **G9**. Issuing declares both gates, so the G5 code fires first | §2.9 places `ERR_SUBSCRIPTION_CANCELLED` in the G5 band; the issue endpoint's subsequence is `G1,G2,G3,G5,G9` | returned `ERR_INVOICE_HAS_NO_LINES` for a cancelled subscription per rung 58, leaving `ERR_SUBSCRIPTION_CANCELLED` dead |
| **F7** credential rungs at reinstatement | **All three enforced**, in rung order 44 -> 45 -> floor: expired COI -> `ERR_VENDOR_COI_EXPIRED`, expired licence -> `ERR_VENDOR_LICENSE_EXPIRED`, rating < 3.0 -> `ERR_VENDOR_RATING_BELOW_FLOOR` | F7: "*the catalogue conditions for those two codes are endpoint-agnostic and would cover it*"; §3.6 lists all three as reinstatement preconditions | left the expiry preconditions unenforced (or routed them to the rating code), making a stated precondition unenforceable |
| **F8** mail-forward line on the overflow branch | **Deliberate asymmetry preserved**: the `ACTIVE -> FORWARDED` edge appends a `MAIL_DISPOSITION` line to the property's draft invoice; the `OVERFLOW -> FORWARDED` edge computes the identical fee and appends nothing | §3.9: "on the `ACTIVE` edge it additionally appends an `ACTIVE` invoice line ... and the declared effects of the `OVERFLOW` edge stop at the fee" | symmetrised, adding a line the OVERFLOW edge's declared effect list does not contain |
| **F9** two rules with no trigger | **Neither enforced.** No code path can emit `ERR_VISIT_TYPE_NOT_COVERED` or `ERR_ENTITLEMENT_EXHAUSTED` | F9: "*nothing forces either rejection on any declared path*"; the entitlement rule "simply falls through to overage pricing" | invented a trigger, refusing schedulings/completions the entitlement rule explicitly lets fall through to overage |
| **F10** unreachable owner status | `Owner.status` is stamped `ACTIVE` at registration and **never written again**; `INACTIVE` is a declared member with no writer. `status` remains an exact-match list filter | §3.1: "Registration always stamps `status` to `ACTIVE`"; F10: "*No transition, endpoint or side effect anywhere writes `INACTIVE`*" | invented a deactivation path (a side effect with no PRD sentence) |
| **F11** freeze fields of a new property | **Derivations run at registration**: a brand-new property reads `freeze_risk_score` **40.0** and `risk_posture` **ELEVATED** (0.0 delta + 25.0 winterization + 15.0 vacancy) | §2.7 side effects: "runs calculations `freeze_risk_score` and `property_risk_posture`"; F11 computes 40.0/ELEVATED explicitly | left the column defaults 0.0/`NORMAL`, contradicting a declared side effect and making the very first `risk-posture` read inconsistent with the formula |
| **F12** routine dispatch with no key | **Routine dispatch succeeds** with `access_blocked_flag` true, no issuance and no grant — identical to the storm pipeline | §3.6 key selection: "no `KeyIssuance` and no `AccessGrant` are created, the new assignment is stamped `access_blocked_flag` true, **and the dispatch itself still succeeds**" — written with no pipeline condition | refused a routine dispatch with an error identifier no catalogue entry names |
| **F13** un-numbered gates vs their own band's rungs | Fixed intra-band order, chosen so each un-numbered code stays reachable: **G5** — terminal -> dedicated-condition code (`ERR_APPROVAL_REQUIRED`, `ERR_TURNOVER_STAGE_INVALID`) -> source-state -> numbered rungs -> remaining un-numbered; **G6** — `ERR_PROPERTY_HAS_OPEN_STORM_HOLD` **before** rungs 34–37 (it gates every seasonal transition, they are action-specific); **G8a** — 43, 44, 45, then `ERR_VENDOR_RATING_BELOW_FLOOR`; **G8b** — `ERR_KEY_REKEY_PENDING` before rung 50, rung 51 before rung 52, `ERR_ACCESS_GRANT_INVALID` before `ERR_GRANT_WINDOW_NOT_OPEN` | F13: "*Determined: the band each un-numbered gate belongs to ... Not determined: its position relative to the numbered rungs of its own band*" | any other intra-band permutation; several permutations (e.g. rung 50 before the rekey check) make a declared code unreachable |

## Reachability audit (hypotheses for downstream verification — re-read the code to check me)

**Codes I believe are unreachable in this implementation**

1. `ERR_VISIT_TYPE_NOT_COVERED` — no code path emits it. Mechanism: F9; visit scheduling's gate subsequence excludes G5 (the band §2.9 assigns it to), and the entitlement rule falls through to overage whenever the type is uncovered, so "the property has no other billing route" is never true.
2. `ERR_ENTITLEMENT_EXHAUSTED` — no endpoint declares "requires a remaining entitlement unit"; visit completion sets `entitlement_applied=false` and prices as overage. F9.
3. `ERR_INVALID_ENUM_VALUE` **for `step_code`** — pre-empted by the dedicated `ERR_WINTERIZATION_STEP_INVALID` check (Adjudication B).
4. `ERR_INVALID_ENUM_VALUE` **for `disposition`** — no endpoint accepts that field.
5. `ERR_VENDOR_NOT_ELIGIBLE`, `ERR_VENDOR_COI_EXPIRED`, `ERR_VENDOR_LICENSE_EXPIRED`, `ERR_VENDOR_NOT_EMERGENCY_CAPABLE` **on `POST /work-orders/{id}/dispatch`** — filtered out by the selector before their own re-check: `vendor_selection` only returns vendors that already satisfy status, both expiries, the rating floor and (on STORM) `emergency_capable`, so rungs 43–46 can only ever pass at dispatch and an empty pool surfaces as rung 47 `ERR_NO_ELIGIBLE_VENDOR`. All four remain reachable on `vendor-assignments/{id}/accept` (43/44/45) and via reinstatement (44/45); **`ERR_VENDOR_NOT_EMERGENCY_CAPABLE` is unreachable everywhere**, since acceptance has no emergency clause.
6. `ERR_INVALID_STATE_TRANSITION` **on turnover advance** — pre-empted by `ERR_TURNOVER_STAGE_INVALID`, which covers every non-successor target (F13/F5 pattern). Reachable on that endpoint only through the two clock preconditions (`CHECKOUT` before `checkout_at`, `CHECKIN` before `checkin_at`).
7. `ERR_INVALID_STATE_TRANSITION` **on work-order dispatch from `PENDING_APPROVAL`** — pre-empted by `ERR_APPROVAL_REQUIRED` (F5). Still reachable from `DRAFT`/`REJECTED`/`DISPATCHED`/`IN_PROGRESS`/`COMPLETED`.
8. `ERR_ALREADY_TERMINAL` **on `POST /invoices/{id}/pay` for a `PAID` invoice** — `PAID` is terminal, so rung 19 fires before rung 58b's "the invoice is not already `PAID`" clause. `ERR_PAYMENT_AMOUNT_INVALID` therefore only ever fires on `amount_cents <= 0`.
9. `ERR_OCCUPANCY_FORBIDS_VISIT`, `ERR_RENTAL_NOT_ENROLLED`, `ERR_SEASONAL_STATE_FORBIDS_OCCUPANCY` **on seasonal transitions** — the endpoint declares G7 but nothing in that band applies; the `occupancy_state == VACANT` preconditions of `BEGIN_CLOSE`/`COMPLETE_WINTERIZATION` are routed to G5 `ERR_INVALID_STATE_TRANSITION` because they reference only the target entity (rung 18's own wording). G7 is inert on this endpoint.
10. **G7 on `POST /work-orders/{id}/dispatch`** — declared in the subsequence; no rung 38–42 applies to a dispatch. Inert.
11. **G9 on `POST /visits/{id}/complete`** — declared; the only G9 code that could apply is `ERR_ENTITLEMENT_EXHAUSTED`, which item 2 above shows is dead. Inert.
12. **G8 on `POST /key-assets/{id}/access-grants`** — declared; rung 51 scopes itself to activation and §3.7 governs capacity at activation only, so no capacity check runs at creation. Inert.
13. `ERR_ALREADY_TERMINAL` **would be globally dead under the literal 18-before-19 ladder order**, because no terminal state of any of the 18 machines is a declared source state. I inverted the pair (terminal check first) so both codes are reachable; this is the single most consequential ordering deviation in the build and is flagged as such.
14. `Owner.status == "INACTIVE"` — unreachable state, F10.
15. **`ERR_ROLE_NOT_PERMITTED` for `Owner` on list endpoints** — rung 4 is enforced only on single-resource and action endpoints where a target exists; list endpoints are not scoped (see resolution 6), so an Owner listing another owner's properties gets 200 with unfiltered rows rather than 403.
16. **`ERR_NOT_RESOURCE_OWNER` on `GET /vendors/{id}`, `/vendor-assignments*`, `/key-issuances*`, `/access-grants*`** — `Owner` is not in those role lists, so rung 4 never applies there.

**Arithmetically-constrained branches**
- `checklist_completion_pct` can only ever be `100.0` on a successful completion (rung 63 forces numerator = `required_item_count`) — the calculation's rounding is exercised but never produces another value.
- The `min(..., FREEZE_RISK_SCORE_MAX)` clamp in `freeze_risk_score` is unreachable: the three terms cap at 60.0 + 25.0 + 15.0 = 100.0 exactly, so the clamp can only ever bind at equality.
- The `min(..., FINDING_SCORE_MAX)` clamp in `finding_escalation_score` is unreachable: max is 50.0 + 24.0 + 20.0 = 94.0.
- `VENDOR_MARKUP_CAP_CENTS` (60000) binds only above a base of ~333k on a managed vendor below the volume tier, or ~400k at 15 %; reachable but only on large parts costs.

## Self-reported resolutions register (open points I had to close)

1. **Gate order vs. resource resolution.** Rung 4/5 (owner/vendor scope, G2) is numbered before rung 7 (path existence, G3), but ownership of a non-existent row is undecidable. Implemented order: rung 3 (role list) -> rung 7 (path ids) -> rungs 4/5/6 (scope, segregation) -> rungs 8–14 (body FKs) -> G4 -> ... For endpoints whose target comes from the **body** (`POST /away-periods`, `POST /visits`), the scope check runs immediately after that FK resolves.
2. **`ERR_ALREADY_TERMINAL` before `ERR_INVALID_STATE_TRANSITION`.** Inverted rungs 18/19 (see audit item 13). Chosen because rung 19 is otherwise provably dead across all 18 machines.
3. **Payload discriminators consumed by earlier gates.** `action`, `to_state`, `to_status`, `step_code`, `revoke_reason`, and OCC `expected_*_version` fields are read before their gate; when absent/wrong-typed/not-a-member the earlier gates are treated as un-evaluable and the request falls straight to the G10 rung that rejects it (`ERR_MISSING_REQUIRED_FIELD` / `ERR_INVALID_FIELD_TYPE` / the field's enum code).
4. **Wrong-typed foreign keys** route to rung 60 `ERR_INVALID_FIELD_TYPE`, not to a 404. A missing required FK routes to rung 59.
5. **Away-period FK order.** Body lists `property_id` then `owner_id`, but rung 8 (owner) is numbered before rung 9 (property); the ladder wins — owner resolves first.
6. **Owner scoping on collections.** Rung 4 is enforced on single-resource reads and actions only. List endpoints are **not** auto-filtered and **not** 403'd for `Owner`; §2.3 defines filters as explicit exact-match predicates and names no implicit scope, and rung 4's remedy is a 403, not a projection.
7. **Un-named preconditions -> `ERR_INVALID_STATE_TRANSITION` (409).** Applied to: `BEGIN_CLOSE`/`COMPLETE_WINTERIZATION` occupancy != VACANT; `ABORT_CLOSE` newest record not NOT_STARTED/PARTIAL; billing-cycle close with a `DISPUTED` invoice on it; work-order submit from DRAFT whose finding is not `WORK_ORDERED`; re-submission from REJECTED with unchanged estimates; work-order complete whose accepted assignment is not `FINISHED`; convert-to-turnover whose turnover is not CLEANING/INSPECTION; on-time return attempted past `return_deadline_at`; `WINDOW_ELAPSED` revoke before the window elapsed; advisory move at/after the landfall ETA; `schedule-sweep` while the event is not WATCH/WARNING/IMMINENT; turnover `CHECKOUT`/`CHECKIN` before their instants; a non-zero `package_delta` from `REQUESTED`.
8. **`POST /visits/{id}/findings` enforces no visit-status precondition** and no `item_code`-in-template check. The endpoint *description* says "against a completed visit" and §3.4 says the code "must appear in the visit's template `item_codes`", but §3 declares no rejection and the catalogue names no code for either. Both are stated claims this implementation does not enforce — flagged as a genuine PRD gap.
9. **Rekey work order created in `PENDING_APPROVAL` without the auto-approve continuation.** Its computed total (8500 + 32500 + 7380 = 48380) is below the 50000 default ceiling, so the submit rule would auto-approve it; §3.7 names the resulting status explicitly, so the named status wins. Its synthesised finding uses `item_code` `"KEY_LOST"` and description `"Key lost; rekey ordered."` (neither is specified).
10. **`LOST -> REKEY_ORDERED` fires inside the first `declare-lost` call** only when `rekey_pending_flag` is false; otherwise the issuance rests in `LOST`.
11. **Storm-assessment cascade (hops 3–8) is best-effort on dispatch.** If `vendor_selection` returns empty during the auto-dispatch, the dispatch is skipped silently and the visit completion still succeeds (a side effect must not 409 its parent request). The auto work order binds `storm_event_id` from the visit's storm response; with no bound response it stays ROUTINE and the auto-approve/auto-dispatch chain does not run.
12. **Dispatch does not re-run the cost chain.** `surcharge_pct_applied` is frozen at dispatch; `storm_surcharge_cents` is (re)computed at submit and at complete, per the calculation's declared triggers. A storm work order therefore carries `storm_surcharge_cents = 0` between submit and complete.
13. **Response-level surcharge freeze happens once**, on the first storm-pipeline dispatch for that response (tracked internally); later dispatches copy the frozen value onto their own work order.
14. **Dispatch key chain window** = the assignment's `[window_start_at, window_end_at]` for both the issuance and the grant; `copies_issued` = 1.
15. **Access-grant creation bumps `KeyAsset.version` on both key types** (§2.10 states one increment per request for the guarded parent), while the code rotation itself is LOCKBOX-only. Key **issuance, return, grant activation and grant revocation do not bump `KeyAsset.version`** — the PRD names version increments explicitly where it wants them and names none for those four.
16. **Pure aggregates are computed on read**, not stored: `lifetime_credit_balance_cents`, `false_alarm_count_window`, `open_critical_finding_count`, `scheduled_visit_count`, `derived_status`, `outstanding_key_count`, `copies_on_hand` / `copies_issued_outstanding` / `copies_lost`, `active_grant_count`, `derived_tier`, `response_count`, `pipeline`, `overdue_days` (while `OVERDUE`). Consequently a re-derivation that writes nothing does **not** bump the parent's version.
17. **`winterization_completeness_pct`, `freeze_risk_score` and `risk_posture` are stored** and re-derived only at the declared points, because `COMPLETE_WINTERIZATION` writes 100.0 directly and would otherwise be overwritten by the newest-record derivation.
18. **Freeze risk is re-derived only on the *return* edges of the occupancy axis** (`OWNER_IN_RESIDENCE->VACANT`, `RENTAL_OCCUPIED->VACANT`, `finish-work`), not on entry into an occupied state. §3.1's summary sentence says "whenever the occupancy axis moves", but its own edge-by-edge enumeration lists the re-derivation on the return edges only and gives a reason for the asymmetry. **Live friction** — the two sentences disagree.
19. **Visit read exposes `duration_minutes`.** §3.4 mandates the value ("A read of a completed visit also exposes a duration in whole minutes") but names no field; the name is my choice, and it is emitted on every visit (0 when either instant is null).
20. **"The property's draft invoice"** (mail forward, false-alarm fee) resolves to the most recently created `DRAFT` invoice for that property; if none exists, no line is appended.
21. **"The property's subscription"** resolves to the newest non-`CANCELLED` subscription, falling back to the newest row when all are cancelled.
22. **Tier change requires an OPEN cycle** (`ERR_NO_OPEN_CYCLE`) — the endpoint declares G9 and the change "takes effect on the open cycle immediately". It sets both `service_plan_id` and `pending_tier_change_plan_id` to the new plan.
23. **Opening the next cycle** sets `prorated_fee_cents` to the in-force plan's `monthly_fee_cents` (not stated for cycle *n*, inferred from activation plus §3.11's "never paused and never had a tier change carries a `prorated_fee_cents` exactly equal to the plan's monthly fee") and refuses a `CANCELLED` subscription with `ERR_SUBSCRIPTION_CANCELLED`.
24. **`refresh-eligibility` requires source `ELIGIBLE`** and always succeeds, stamping `last_eligibility_evaluated_at`; it drops to `LAPSED` only when an expiry has passed.
25. **Access-grant capacity uses the closed-interval *overlap* count** (§3.7's elaboration), not the bare ACTIVE count of rung 51's one-line form.
26. **Incident investigation** picks the supplied `checklist_template_id`, else the earliest ACTIVE `ALARM_RESPONSE` template, else creates no visit; an unresolvable supplied template -> `ERR_LINKED_RESOURCE_NOT_FOUND`. Default window = clock -> clock + 24 h.
27. **`ERR_MAIL_HOLD_NOT_STARTED` is checked on every `log-packages` call**, not just the activation edge (the catalogue condition is unqualified; the clock's monotonicity makes the two equivalent in practice).
28. **`ERR_FORWARDING_ADDRESS_MISSING` and `ERR_HOLD_TOO_LONG` on extension are enforced** even though `forward` and `extend` declare no G10 in their gate subsequences — both are explicit §3.9 preconditions and dropping them would make two catalogue codes dead.
29. **`current_code` is forced to null for `PHYSICAL` keys** at registration (§3.7: "`current_code` is null for physical keys"), discarding a supplied value.
30. **`checklist_templates.item_codes` non-emptiness/uniqueness and `state_code` two-uppercase-letter format are not enforced** — declared as constraints with no error code anywhere.
31. **Invoice void from `DRAFT` skips the `amount_paid_cents == 0` check** (§3.11: "voiding a draft invoice has no such precondition"); `PARTIALLY_PAID -> VOID` is not a declared edge and returns `ERR_INVALID_STATE_TRANSITION`.
32. **Unknown routes and disallowed methods** return `ERR_RESOURCE_NOT_FOUND` (404) in the standard error envelope.

## Item-11 sanity checks

- **Compile/AST**: all 22 `.py` files compile — `OK app.py ... OK serialize.py`, 0 failures.
- **`bash start.sh` boot**: `PORT=18952 bash start.sh` serves `GET /property-care/_clock` -> `{"current_utc":"2026-05-01T00:00:00.000Z"}` and `POST /property-care/owners` -> 201 within 2 s. An 8-round kill-and-relaunch loop on one port succeeded 8/8, each ready in <= 6 x 100 ms polls (bounded 40 x 50 ms `EADDRINUSE` retry around `make_server`; no sleeps, no pre-bind).
- **Persistence grep**: no matches. Storage is `core.db.data`, a dict of dicts built empty at import; nothing is seeded at startup.
- **Route diff**: MISSING 0 / EXTRA 0 (pasted verbatim above).
- **Behavioural smoke**: three scripted end-to-end suites (~200 assertions) all report `FAILURES: 0`, covering the pinned numbers — tier-change proration 31453 (per-leg rounding), work-order chain 29750/7515/49265, storm chain surcharge 17243 / total 66508, per-line tax 88+88=176 and -88, entitled vs overage visit pricing (1500 / 3800 / 14850+2500+3800), the non-monotone false-alarm ladder (0/5000/15000/10000/25000), freeze risk 40.0->82.0->15.0, storm tiers and both deadline anchors, lockbox rotation `0001`->`0002` with `CODE_ROTATION` invalidation, key overdue/lost/rekey, half-open turnover overlap (touching edge passes, +1 min collides), and all three OCC 412s plus the minted storm-response 412.

**Orchestrator verification:** 5,385 lines of `.py` on disk across `workspace/implementation/`; `grep -rEn 'sqlite|json\.dump|pickle|/tmp'` returns nothing.

## Step 7: Run tests and iterate — 2026-08-09T18:35:00.000Z

Done — clean 8-round sweep, 181/181 in every round.

## Summary

**Iterations:** 1 diagnostic smoke round (~3.5 min, 178/182) -> one fix batch -> 1 full 8-round sweep (~7.2 min wall, two waves of four), **8/8 rounds green, zero fixes needed on the second pass**. No flakiness: the failing set was identical and deterministic across rounds, and the union of failures after the fix batch was empty.

**Host contention:** the first sweep attempt was aborted before launch — `pgrep` showed 10 foreign runners across tasks 0949/0952/0953 at load 13.8. I polled until the host drained to <=2 foreign runners (load 5.4) and only then launched. No SIGTERM/exit-143 artifacts resulted.

### Tests deleted (1)
- `test_04_visit_completion_and_pricing.py::test_cycle_cannot_close_while_a_bound_visit_is_in_progress` — **unique-derivability collapse**. The rule (PRD rung 30 / §3.2) reads "no visit **bound to that cycle** is in status `EN_ROUTE` or `IN_PROGRESS`". The PRD's own vocabulary makes "bound to X" the FK relation (§3.3: "a `rental_turnover_id` when the visit is **bound to** a turnover"), and it states that a visit is "born ... with a null `billing_cycle_id`" (§3.3) which is "stamped" only at **hop one of completion** (§3.4), with `COMPLETED` terminal. Under that faithful reading no `EN_ROUTE`/`IN_PROGRESS` visit is ever bound to a cycle, so a PRD-only implementer legitimately produces code on which this test fails. The PRD deliberately words the sibling rule differently ("no visit **on the property**" for subscription cancel, §3.2), which reinforces the FK reading. Consequence worth flagging downstream: `ERR_CYCLE_HAS_LIVE_VISIT` is **dead code** under the literal reading.

### Fixes to `test_suite/` (3)
- `test_02_subscriptions_and_billing_cycles.py::test_carry_capped_close_carries_two_units_into_the_next_cycle` — `validate_success(...)` -> `validate_success(..., 201)`. PRD §4 endpoint table pins `POST /property-care/subscriptions/{id}/billing-cycles` at **201**; the test defaulted to 200.
- `test_02_...::test_expire_close_carries_nothing_into_the_next_cycle` — same 201 correction (sibling of the above; swept the file for other bare `validate_success` calls on 201 endpoints and found none).
- `test_05_findings_and_work_orders.py::test_second_work_order_replaying_the_pre_create_finding_version_is_stale` — expected work-order status `PENDING_APPROVAL` -> **`APPROVED`**. The test's own asserted total is 25960 (2.0 h x 8500 + 5000 = base 22000, +18 % managed markup 3960), which is <= the default routine ceiling of 50000, so PRD §3.5's approval fork says the order "**continues to `APPROVED` inside the same submitting request**". Every sibling test in the file that asserts `PENDING_APPROVAL` has a total above its ceiling (113280, 140300, 316250), confirming the outlier. Added an inline comment showing the arithmetic.

### Fixes to `test_helpers/` — none
No fixture, factory or header-builder bug surfaced; no failure cluster shared a setup trace.

### Fixes to `implementation/` — none
All four failures were test-artifact defects or a non-derivable assertion. No implementation check was weakened, no endpoint/field/side-effect added, storage remains in-memory only.

### Falsification runs
None were needed — no failure had the shape of saturation, a port collision or a boot flake. All four were deterministic assertion failures reproducing identically across the smoke round and carrying concrete response bodies, and all four were explained by PRD text rather than by the harness. The pre-launch drain wait was the contention control instead.

### Fairness flags on passing tests — **none found**
A full independent audit of all 12 test files plus `assertions.py`/`fixtures.py`/`factories.py`/`types.py` against PRD.md turned up **zero** un-grounded assertions. This suite is unusually disciplined about the PRD's 13 declared frictions — each is handled one of three ways, verified in the code rather than taken on trust:
- **Not exercised at all:** `duration_minutes` (the impl-invented field name) appears nowhere in the suite; the synthesised rekey finding's `"KEY_LOST"` item_code and literal description are never asserted (only the too-early `declare-lost` 409 path is tested); `ERR_APPROVAL_REQUIRED` (F5), `ERR_GRANT_WINDOW_NOT_OPEN` (F4), `ERR_KEY_REKEY_PENDING` (F3), `ERR_SUBSCRIPTION_CANCELLED` on issue (F6) and the reinstatement credential codes (F7) have zero occurrences.
- **Relaxed to a set:** the rung-18/19 ordering question (the impl's single most consequential deviation — it inverted `ERR_ALREADY_TERMINAL` before `ERR_INVALID_STATE_TRANSITION` to keep both reachable) is always asserted via `validate_error_is_one_of([...])`, never as a single literal.
- **De-ambiguated in the fixture:** incident `investigate` calls always supply an explicit `checklist_template_id` and window rather than leaning on the undetermined 24-hour default; routine-dispatch fixtures always register a key asset first, sidestepping F12; invoice lines are appended manually wherever F2's auto-vs-manual question would arise; and no scenario ever creates two candidate subscriptions or two DRAFT invoices, so the impl's "newest non-CANCELLED" / "most recent DRAFT" tie-breaks are never load-bearing.
- F11 specifically: no test reads back a **freshly registered** property's `freeze_risk_score`/`risk_posture`, so the 0.0/`NORMAL`-vs-40.0/`ELEVATED` question stays open as the PRD intends; every freeze-risk assertion follows an explicit temperature or winterization event that pins the formula.

### Final tallies
- Tests collected: **181** (182 before the one deletion).
- Per-round pass counts: **181 / 181 / 181 / 181 / 181 / 181 / 181 / 181** — 0 failed, 0 errors in all eight rounds.

**Orchestrator verification:** all 8 `results.N.json` parsed independently — each `passed=181 total=181 failed=0` with **181 individual test rows**, and all 8 name sets **identical**. `def test_` count on disk = 181, `Design:` tag count = 181, zero `@pytest.mark` of any kind.

## Step 8: Finalize PRD — 2026-08-09T19:15:00.000Z

`PRD_FINALIZED.md` is written. Hand-off was routed as a **three-part diff** (Part A = Step 7 fixes; Part B = impl-gen's timestamp/error-routing adjudications + F1–F13 adjudications + reachability audit + 32-item resolutions register; Part C = test-gen's 7 skipped instances + 13-entry near-miss register), assembled by the orchestrator into a scratchpad hand-off file.

## Size
`PRD.md` 977 lines / 25,988 words -> `PRD_FINALIZED.md` 1,001 lines / 31,597 words (**+2.5 % lines, +21.6 % words**, 74 diff hunks, no section added or removed, no wholesale rewrite).

## Changes (section — kind — what — impl anchor)

**Global (§2)**
- §2.2 — revise — `api_request_timestamp` is real wall-clock, not the logical clock — `core.py:424`
- §2.2 — insert — unknown route / disallowed method -> `ERR_RESOURCE_NOT_FOUND` 404 in the standard envelope — `app.py:38-44`
- §2.4 — insert — one uniform instant rendering (`...S.mmmZ`) for *every* datetime field incl. echoed caller input; strict parsing (mandatory `T` + zone, 0–6 fractional digits), malformed -> `ERR_INVALID_FIELD_TYPE` — `core.py:256-300`, `serialize.py` (all fields)
- §2.4 — insert — the closed list of **read-time aggregates** and the rule that re-deriving one never bumps `version` — `serialize.py:30,51-52,112-113,156,187,199,242-247,261,350,354`
- §2.7 G2 — revise — role-list check first; scope check deferred until the target resolves; **list endpoints are never scoped or filtered** — `gates.py:36-45`, all `list_response` sites
- §2.7 G3 — revise — body-FK order yields to rung numbering (owner before property); wrong-typed FK -> rung 60, not 404 — `catalog.py:25-30`, `gates.py:95-108`
- §2.7 — insert — **payload-discriminator rule**: enum discriminators pre-empt the gates that depend on them; expected-version fields are compared only when an integer is supplied — `gates.py:253-267` vs `workorders.py:50-53`
- §2.7 table — revise — added **G10** to mail-hold `forward` and `extend` — `facilities.py:358,385`
- §2.8 r4 — revise — scope applies only to single-resource/action targets that chain to an owner — `gates.py:42-45`
- §2.8 r18 — insert — rung 18 is the catch-all for the 14 un-named target-entity preconditions; those sit after the source check and after any competing numbered rung
- §2.8 r19 — insert — **rungs 18/19 evaluated in reverse order** (terminal first) — `gates.py:114-126`
- §2.8 r30 — insert — both arms are unreachable, with the reasons (`ISSUED` never carries a positive `amount_paid_cents`; `billing_cycle_id` is stamped only at completion) — `invoices.py:199-205`, `subscriptions.py:331-333`
- §2.8 r50/51/52 — revise — F3 and F4 splits, capacity uses §3.7's closed-interval count, creation runs no capacity test — `keys.py:98-103,245-257`, `workorders.py:322-332`
- §2.8 r58 — revise — cancellation is G5 and fires first; the `PAID` half is pre-empted by rung 19 — `invoices.py:136-140,153-157`
- §2.8 r61 — revise — closed list corrected: `step_code` and `disposition` **out**, `default_finding_category` **in**; `to_status` per-endpoint; `status` never membership-checked — `gates.py:140-163`, `catalog.py:103-104`
- §2.8 r62 — revise — added `approval_ceiling_override_cents`; named the fields deliberately *not* range-checked and where their constraints live instead — `gates.py:166-180`
- §2.9 — revise — `ERR_VISIT_TYPE_NOT_COVERED` and `ERR_ENTITLEMENT_EXHAUSTED` catalogued but never emitted
- §2.10 — revise/insert — **four** OCC guards; the storm-response guard, its 412 identifier and its band position; the "integer-only comparison" rule — `storms.py:244-248`
- §2.11 — insert — the three identities that presuppose an operator-appended line are not enforced (F2 governing clause) — `calc.py:637-657` callers
- §2.12 + §1 — revise — the fifth "divergence" is **no divergence**: both pipelines dispatch key-less identically — `ops.py:162-167`

**§2.13 — all thirteen frictions closed** (table below), plus the intro rewritten from "recorded rather than resolved" to "every point is now adjudicated".

**§3**
- §3.1 — revise x5 — `INACTIVE` has no writer; `state_code`/`primary_residence_state` format unenforced; **freeze-risk trigger set rewritten**; `winterization_completeness_pct` and `storm_hold_flag` are stored with named recompute points; `lifetime_credit_balance_cents` bumps no version — `properties.py:53-62,93,185-201,236-247`, `facilities.py:135-139,160-164,239-242`, `ops.py:280-293`
- §3.2 — insert x3 — resolution of "the property's subscription"; tier change needs an OPEN cycle and writes both plan fields; next-cycle opening (`ERR_SUBSCRIPTION_CANCELLED`, full monthly fee, carry-in source) — `calc.py:18-25`, `subscriptions.py:164-201,271-306`
- §3.3 — insert — `item_codes` non-emptiness/uniqueness, `critical_item_codes` subset and `status` membership are **not** validated — `catalog.py:99-116`
- §3.4 — revise x3 — the duration field is named **`duration_minutes`** and is present on every visit read; storm cascade details (event id from the bound response, storm-ceiling-only auto-approve, **best-effort dispatch**); manual finding enforces **neither** precondition — `serialize.py:156`, `visits.py:216-233,342-355`
- §3.5 — insert — the cost chain runs at exactly four moments and **not at dispatch**, so a storm WO carries `storm_surcharge_cents` 0 between submit and complete — `ops.py:133-160`, `workorders.py:206`
- §3.6 — revise x5 — F7 codes and order at reinstatement; refresh-eligibility source/no-op case; rungs 43–46 unreachable at dispatch and `ERR_VENDOR_NOT_EMERGENCY_CAPABLE` globally dead; the dispatch key chain (**one copy, grant window = assignment window**, deadline from the clock); response-level surcharge freeze happens once — `vendors.py:99-126`, `calc.py:376-403`, `ops.py:113-168`
- §3.7 — revise x5 — `current_code` discarded for `PHYSICAL`; **`KeyAsset.version` movement rule**; issuance's three ordered custody checks; loss/rekey detail (rest-in-`LOST` branch, literal `item_code`/`description`, finding -> `WORK_ORDERED`, total 48380, stays `PENDING_APPROVAL`); activation order + `ERR_GRANT_WINDOW_NOT_OPEN` — `keys.py:29-42,95-103,161-198,245-257`, `ops.py:209-229`
- §3.9 — revise x3 — start-date check on every `log-packages` call; "the property's draft invoice" = newest `DRAFT`; investigation template/window fallbacks and the fact the forced visit bypasses the scheduling gates — `facilities.py:329-335`, `calc.py:58-62`, `incidents.py:82-97`
- §3.10 — revise — assessment gate order and the 412 identifier — `storms.py:237-253`
- §3.11 — revise x3 — issuing order (F6); void source states and why `ERR_INVOICE_ALREADY_PAID` is dead; line-void has no state gate — `invoices.py:129-145,199-214,113-126`
- §4 — revise — `POST /visits/{id}/findings` description no longer claims "completed visit"
- §5 — insert — `ERR_STALE_STORM_RESPONSE_VERSION` | 412

## F1–F13: the side the code actually takes (verified in source)

| # | Verified behaviour in `implementation/` | Edited |
|---|---|---|
| F1 | `ERR_STALE_STORM_RESPONSE_VERSION`, 412, in G4 — **after** SoD (rung 6), before G5; skipped when the field isn't an integer (`storms.py:244-248`) | §2.13, §2.10, §3.10, §5 |
| F2 | No auto-append of `VISIT_OVERAGE`/`GUARANTEE_CREDIT`/`ENTITLEMENT_OFFSET`; only 4 auto line types | §2.13, §2.11 |
| F3 | Split, **rekey first**: `ERR_KEY_REKEY_PENDING` then `ERR_KEY_COPIES_UNAVAILABLE`, both after rung 49 (`keys.py:95-103`) | §2.13, r50, §3.7 |
| F4 | Split; activation order = capacity -> rotation -> window; start-work: no grant -> `ERR_ACCESS_GRANT_INVALID`, none in-window -> `ERR_GRANT_WINDOW_NOT_OPEN` | §2.13, r51/r52, §3.7 |
| F5 | `ERR_APPROVAL_REQUIRED`, between terminal and rung 18 (`workorders.py:165-170`) | §2.13 |
| F6 | `ERR_SUBSCRIPTION_CANCELLED` (G5) before the line test (`invoices.py:136-140`) | §2.13, r58, §3.11 |
| F7 | All three, order 44 -> 45 -> rating floor (`vendors.py:105-110`) | §2.13, §3.6 |
| F8 | Asymmetry preserved: `ACTIVE` edge appends, `OVERFLOW` edge does not (`facilities.py:364-369`) | §2.13 (§3.9 clause reinforced) |
| F9 | Neither identifier is raised anywhere (grep-verified) | §2.13, §2.9 |
| F10 | `status` written once at registration; no `INACTIVE` writer | §2.13, §3.1 |
| F11 | `rederive_risk` runs at registration -> **40.0 / `ELEVATED`**, `version` still 1 (`properties.py:62`) | §2.13, §3.1 |
| F12 | Routine dispatch with no key **succeeds**, `access_blocked_flag` true (`ops.py:162-167`) | §2.13, §2.12, §1, §3.6 |
| F13 | Verified per band — see refutation #1; my pin differs from Part B1 | §2.13, r18/r19 |

## Refutations — Part B / Part C claims checked and found wrong or overstated

1. **B1 F13's G5 rule is overstated.** The claimed general order ("terminal -> dedicated-condition code -> source-state -> numbered rungs -> remaining un-numbered") holds at **only two** endpoints — work-order dispatch and turnover advance. Everywhere else the un-numbered G5 gate sits *after* rungs 19/18: `ERR_STEP_ALREADY_RECORDED`, `ERR_ISSUANCE_NOT_OVERDUE`, `ERR_LOST_THRESHOLD_NOT_MET`, `ERR_PACKAGES_OUTSTANDING`, `ERR_MAIL_HOLD_NOT_STARTED`, `ERR_SEVERITY_TOO_LOW_TO_ESCALATE`, `ERR_INCIDENT_NOT_ALARM_CLASS`, `ERR_PLAN_RETIRED`, `ERR_VISIT_IN_FLIGHT`, `ERR_STORM_CEILING_EXCEEDED`, `ERR_SUBSCRIPTION_CANCELLED` on issue. Pinned the corrected rule with the two named exceptions.
2. **B0's rung-61 "no other field routes here" is false.** `catalog.py:103-104` passes `enum_overrides={"default_finding_category": core.CATEGORIES}` and routes that failure to `ERR_INVALID_ENUM_VALUE`. The closed list in §2.8 now includes it.
3. **C2 #6 is refuted: rung 23 (`ERR_FINDING_HAS_LIVE_WORK_ORDER`) is reachable.** Reject a `PENDING_APPROVAL` work order -> finding returns to `TRIAGED`, WO becomes `REJECTED`; re-submit with revised estimates -> WO becomes `DRAFT` while the finding **stays** `TRIAGED`; `DRAFT` is not in {`REJECTED`,`VOID`}, so dismissing the finding fires rung 23. No PRD edit needed.
4. **B3 #15 is incomplete.** Two operations DO bump `KeyAsset.version`: `declare-lost` calls `touch(key)` unconditionally (`keys.py:178`), and rekey work-order completion bumps it when clearing the flag (`workorders.py:210-212`).
5. **C1 #4's arithmetic is wrong.** Rekey work-order total is **48380** (1.0 h x 8500 + 32500 = 41000 base, 18 % managed markup 7380), not 48970.
6. **B2 #5 understates the dead zone.** `ERR_VENDOR_NOT_EMERGENCY_CAPABLE` is dead **everywhere** (raised at no site at all), not merely pre-empted at dispatch.
7. **B2 #8 is right for the wrong reason and under-scoped.** `ERR_INVOICE_ALREADY_PAID` is unreachable because **`ISSUED` can never carry a positive `amount_paid_cents`** — the first partial payment moves the invoice to `PARTIALLY_PAID`, which is not a declared void source state. A genuinely part-paid invoice offered for voiding answers `ERR_INVALID_STATE_TRANSITION` — a PRD/impl mismatch B2 did not name.
8. **B3 #25 is not an open point.** §3.7 already stated the closed-interval overlap geometry; only rung 51's one-line form was loose.
9. **B3 #7's list omits three sites** also routing to `ERR_INVALID_STATE_TRANSITION`: a non-declared advisory edge, a non-declared occupancy edge, and a seasonal action whose source doesn't match.
10. **Part A's `ERR_CYCLE_HAS_LIVE_VISIT` flag is confirmed** (dead under the FK reading) **but needs no PRD change** — rung 30 and §3.2 already word it as the FK relation.

## Per-edit pre-edit search log (condensed; (a) subject / (b) impl paths / (c) siblings swept / (d) wording adjustment)

- **Envelope timestamp** — (a) source of `api_request_timestamp`; (b) `core._request_timestamp`, `core.now`, `core.set_clock`; (c) every other envelope + `data` timestamp; (d) scoped the claim to the envelope.
- **Instant rendering/parsing** — (a) datetime I/O; (b) `core.fmt_iso`, `core.parse_iso`, `gates._type_ok`, 60+ `fmt_iso` sites, `system.set_clock`; (c) every echoed and derived instant; (d) added "and the `current_utc` the clock capabilities report".
- **G2/G3 ordering** — (a) resolution order vs scope; (b) `gates.begin/fetch_path/owner_scope/vendor_scope/fetch_body_fk` + every route's first ten lines; (c) all 30 `owner_scope` and all 24 `list_response` sites; (d) split the gate into role-list half and scope half.
- **Discriminator rule** — (a) G10 fields read by earlier gates; (b) `gates.enum_discriminator` + 6 call sites, the 4 `expected_*_version` blocks; (c) `visit_type` fallback branch; (d) added "It is not read ahead of G3".
- **Rung 18/19 + catch-alls** — (a) state-gate ordering; (b) `gates.check_state` + all 40 call sites + the 5 bypassing endpoints; (c) every un-named precondition in every route module; (d) added the "identifier but not position; numbered rung first" clause.
- **Rung 30** — (b) `invoices.void_invoice/pay/dispute/resolve_dispute`, `subscriptions.close_cycle`, `visits.complete` hop one; (c) every writer of `amount_paid_cents` and `billing_cycle_id`; (d) none.
- **Rungs 50/51/52 + §3.7** — (b) `keys.create_issuance/activate_grant/create_grant`, `workorders.start_work`, `calc.access_grant_capacity_ok`, `ops.create_access_grant`; (c) rung 49 at both sites, creation vs activation, the `PHYSICAL` path; (d) said the rotation check "governs the search for a usable grant" at start-work.
- **Rung 61/62** — (b) `gates.ENUM_MEMBERS`, `NUMERIC_RANGES`, `validate_payload`, every `enum_overrides` use; (c) every `validate_payload` spec in all 15 route modules; (d) replaced "any magnitude and sign" with the three named alternative identifiers.
- **Read-time aggregates / version** — (b) all of `serialize.py`, `core.touch`, `calc` derivations; (c) split out the three that ARE stored; (d) softened "does not touch that row at all" to "is never on its own a reason to write the row".
- **Freeze-risk triggers** — (b) all 8 `rederive_risk` call sites; (c) every occupancy writer incl. `facilities.advance_turnover` and `ops.occupancy_from_contractor`, all 5 seasonal actions, `patch_property`; (d) generalised to "entry into `VACANT`, by whichever driver".
- **§3.4/§3.5 cascade + chain timing** — (b) `visits.complete:216-233`, `ops.submit_work_order/perform_dispatch/freeze_storm_surcharge`, all 4 `run_cost_chain` sites; (c) `workorders.submit/approve/reject/complete/invoice`; (d) added the "no storm response -> ROUTINE -> rests in `PENDING_APPROVAL`" branch.
- **§3.6 dispatch key chain** — (b) `ops.perform_dispatch`, `create_key_issuance`, `create_access_grant`, `calc.key_selection`, `key_return_deadline`; (c) the manual issuance and manual grant endpoints; (d) separated the grant window from the issuance deadline.
- All remaining edits followed the same pattern with no further wording retreat.

**Orchestrator verification:** `PRD_FINALIZED.md` 1,001 lines vs `PRD.md` 977. `find -newer results.8.json` over `implementation/`, `test_suite/`, `test_helpers/` returns only two sibling `results.N.json` files — **Step 8 touched documentation only**.

## Step 9: Complete PRD — 2026-08-10 (two passes; first pass killed by an API session limit)

**Pass 1** walked `implementation/` in full and applied **30 hunks** (through §3.9, PRD line ~688) before being terminated mid-run by "session limit · resets 8pm UTC". Disk was measured before reacting: `PRD_COMPLETED.md` was intact at 1,001 lines with all 30 hunks written. **Pass 2** was a bounded FRESH subagent told to continue in place (explicitly forbidden from re-copying `PRD_FINALIZED.md`, which would have destroyed the 30 edits) and to cover the unvisited tail (§3.9 tail, §3.10, §3.11, §4, §5) plus re-verify the thinly-scanned middle (§2.8's 68 rungs, §2.9–§2.13).

Scan complete. Final state verified: 32 headings, 142 endpoint rows (== `app.url_map`), 99 error rows (== `core.ERROR_STATUS`, same order, same statuses).

## Totals

| | |
|---|---|
| `PRD_FINALIZED.md` | 1001 lines, 227,576 chars |
| `PRD_COMPLETED.md` | 1001 lines, 251,080 chars (**+23,504**) |
| Total hunks | **54** (pass 1's 30 + pass 2's 27 edits, two of which land in one adjacent hunk) |
| Pass-2 ambiguity-pins | 10 |
| Pass-2 mismatch-revisions | 17 |

## Pass-2 changes

- §2.7 G3 — insert — mismatch — the universal "a wrong-typed body FK is left for rung 60" now names its one exception — `routes/incidents.py:72`
- §2.8 rung 11 — revise — mismatch — `ERR_TEMPLATE_NOT_FOUND` also fires at secure-sweep scheduling — `routes/storms.py:198`
- §2.8 rung 13 — revise — mismatch — invoice-line appending addresses its invoice by **path** id, so it answers rung 7, never `ERR_INVOICE_NOT_FOUND`; work-order invoicing is the rung's only site — `routes/invoices.py:70`
- §2.8 rung 14 — insert — ambiguity — `rental_turnover_id` is *required* on conversion yet still carries rung 14's 404 — `routes/visits.py:311`
- §2.8 rung 46 — insert — mismatch — **rungs 43–46 are unfailable at dispatch** (all four are pool filters inside vendor selection); 43/44/45 fire only at acceptance, 44/45 at reinstatement, and 46 is a *third* dead identifier — `calc.py:376`
- §2.8 rung 53 — insert — ambiguity — visit scheduling resolves the property's subscription, invoice opening reads the cycle's own `subscription_id` — `routes/invoices.py:19`
- §2.8 rung 55 — revise — mismatch — also applies to **tier change**; the resume half is unreachable (`PAUSED` implies `paused_at` set) — `routes/subscriptions.py:185`
- §2.8 rung 68 — revise — mismatch — `ALL_REQUIRED` with no `thermostat_f` answers `ERR_WINTERIZATION_STEP_INVALID`, tested ahead of the below-minimum test — `routes/facilities.py:107`
- §2.11 — revise — mismatch — entitlement-unit conservation is broken by the tier-change zero floor §3.2 itself pins — `calc.py:252`
- §2.11 — revise — mismatch — "voiding that line and re-invoicing reproduces the same amount" is unexercisable; `INVOICED` is terminal — `routes/workorders.py:233`
- §2.11 — revise — mismatch — a rotation invalidates only `PENDING`/`ACTIVE` grants — `ops.py:201`
- §2.11 — insert — mismatch — false-alarm ledger conservation is conditional on a `DRAFT` invoice existing — `routes/incidents.py:143`
- §3.5 — revise — mismatch — the cost chain runs at **five** moments, not four (the `STORM_ASSESS` continuation) — `routes/visits.py:227`
- §3.5 — insert — ambiguity — **rejection carries no pipeline rule at all**, and the finding return is conditional — `routes/workorders.py:142`
- §3.6 — revise — mismatch — acceptance re-tests both credential expiries; the five conditions' exact order; `rating` is *not* re-tested — `routes/workorders.py:267`
- §3.6 — insert — ambiguity — withdrawal leaves the key issuance in `ISSUED` (unlike a decline) — `routes/workorders.py:361`
- §3.7 — insert — ambiguity — a `PHYSICAL`-key grant rotates nothing and is born with a null `code_snapshot`; version still bumps — `ops.py:209`
- §3.9 — insert — ambiguity — the `CHECKIN` flip bypasses rung 41's enrolment/seasonal preconditions; both flips bump `Property.version` — `routes/facilities.py:249`
- §3.9 — insert — mismatch — a non-string `checklist_template_id` yields 404 — `routes/incidents.py:72`
- §3.10 — revise — mismatch — **enrolment performs no region comparison**; the only site is sweep scheduling — `routes/storms.py:150`
- §3.10 — revise — mismatch — secondary landfall touches **no** response, so a past-deadline `SECURE_SWEEP_SCHEDULED` is not settled — `routes/storms.py:87`
- §3.10 — insert — ambiguity — sweep scheduling runs the `STORM_SECURE` occupancy gate; the lead is picked by **`derived_tier`, not `status`**; the created window is not interval-checked — `routes/storms.py:210`, `calc.py:542`
- §3.10 — revise — ambiguity — the frozen surcharge reads `derived_tier`, not `status`; the freeze attaches to the earliest-created matching response — `calc.py:569`, `ops.py:118`
- §3.11 — revise — mismatch — the recompute trigger list — `subscriptions.py:234`, `invoices.py:212`
- §3.11 — revise — mismatch — the "cycle in OPEN/CLOSING/CLOSED" requirement at issuing is **vacuous and unenforced** — `routes/invoices.py:129`
- §3.11 — insert — mismatch — dispute's `resolution_note` is discarded; **`late_fee_cents` survives a void**, so totals are not recomputed to zero — `invoices.py:180,212`
- §4 header — revise — mismatch — the 201/200 rule restated correctly, with the 9+13 enumeration

## Refutation list (claims checked and found false/overstated)

**In `PRD_FINALIZED.md`:**
1. Rung 13 "applies to work-order invoicing **and to invoice-line appending**" — false; append uses `fetch_path` -> `ERR_RESOURCE_NOT_FOUND`.
2. Rungs 43–45 "applies to work-order dispatch and to assignment acceptance", rung 46 "applies to work-order dispatch" — all four can never fail at dispatch; rung 46 is never emitted anywhere.
3. Rung 55 "This applies to pause and to resume" — omits tier change; and its resume half is structurally unreachable.
4. Rung 11 "This applies to visit scheduling" — also secure-sweep scheduling.
5. §2.7 G3 "a wrong-typed FK ... does not produce a 404" — one endpoint contradicts it.
6. §2.11 entitlement-unit conservation "holds at every instant regardless" — broken by the tier-change floor.
7. §2.11 work-order cost conservation "voiding that line and re-invoicing reproduces the same amount" — unreachable.
8. §2.11 access-grant conservation "invalidates **every** grant whose index is lower" — only `PENDING`/`ACTIVE`.
9. §2.11 false-alarm ledger conservation — silently conditional on a `DRAFT` invoice.
10. §3.5 "evaluated at **exactly four moments**" — five (a counting claim about itself).
11. §3.6 acceptance preconditions — omitted the two credential-expiry tests the code performs.
12. §3.10 "Only properties whose `state_code` matches `region_state_code` may receive a response" — enrolment does not check.
13. §3.10 secondary landfall — the "not rewound" claim is true but the sentence implied only `ASSESSMENT_DUE` was spared; the whole settlement block is skipped.
14. §3.10 "the tier at scheduling" / "the event's current tier" — ambiguous between `status` and `derived_tier`; the code reads `derived_tier`, and §3.10 itself says the two may disagree. **The highest-consequence finding of this scan.**
15. §3.11 "requires the parent billing cycle to be in OPEN, CLOSING or CLOSED" — no such check; vacuous.
16. §3.11 "the totals recomputed to zero" on void — false when a late fee exists.
17. §4 "**A request that mints a new resource answers 201 Created**" — false for ~9 endpoints that mint rows as side effects.

**Claims the PRD makes about itself that turned out wrong:** #1, #2, #3, #4 (scope-of-application claims in the ladder), #10 ("exactly four moments"), #17 ("a request that mints a new resource"), and the §2.11 "eleven identities must hold after every mutation" framing (three of the eleven, not one, need the qualification §2.11 gives only to three others).

**In pass 1's 30 hunks:** none refuted. All re-checked against the code and confirmed — including line 21 (`PlatformAdmin` escapes rung 4 and the pipeline rule), line 494's "four departures, and only four" (all 30 G5-bearing endpoints walked; the count is right), line 528 (sweep settlement prefers the response's bound subscription), line 564 (0.0 on an empty template), line 646 (`overdue_days` recomputed before the threshold test), line 664 (`BEGIN_OPEN`'s full reopen). Three were extended in place (rung 14, §3.5 rejection, §3.6 withdrawal) rather than corrected.

## Priority-3 cross-cutting sweeps

- **8-hop cascade in code order** (`routes/visits.py:153–263`): walked hop by hop. Legs that do not fire: hops 3–8 unless `visit_type == STORM_ASSESS`; the auto-approve leg unless pipeline is `STORM` and total <= 250000; the dispatch leg is best-effort (`raise_on_empty=False`); hops 5–8 skipped entirely when key selection is empty. All already pinned by pass 1 at line 576. The *summary* sentences at 566/578 check out against their detail. **One new finding:** the cascade's work-order submission is a fifth `run_cost_chain` site the §3.5 summary omitted.
- **PRD claims about itself** — 7 refuted, listed above. Counting claims verified as *correct*: "four departures and only four", "ten gates", "sixty-eight rungs", "six rung numbers carry two rows", "the line types appended automatically are exactly four" (F2 — grep confirms exactly 4 non-operator `append_invoice_line` sites), "eleven conservation invariants".
- **Response-field projections** — diffed all 23 serializers in `serialize.py` against §3. **Nothing.** Every read-time aggregate §2.4 lists is computed live and no other field is; no serializer leaks a private field (`_surcharge_frozen`, `_seq`, `_collection` all excluded); no documented field is missing.
- **List tie-breaks** — `core.rows()` sorts `(created_at, _seq)` everywhere; pass 1's line-95 pin covers it. `invoice_lines_of` sorts by `(sequence_index, _seq)`; false-alarm peers by `(reported_at, created_at, _seq)`; vendor pool by `(-rating, hourly_rate, created_at, _seq)`; key pool by `(LOCKBOX-first, created_at, _seq)`. All documented. **Nothing new.**
- **Version-bump counts** — all four OCC guards verified at exactly one bump per mutated row per request, and **all four serialize after `touch()`**, so mutation responses carry post-mutation `version`. The version-observability bug of 0920/0948 is **not** present here.
- **Defaults / boundary inclusivity / rounding order** — checked every optional input's server-side default and every `<` vs `<=` against §3. All match (travel zone `<=`; storm tier strict `>`; sweep timeliness `<=`; grant window closed; turnover overlap half-open strict; overflow `>=6`; approval `>` ceiling; delinquency `<=` 21 days; freeze breach strict `<`; posture bands `>=`). Rounding orders (per-leg proration, per-line tax, surcharge-after-offset, markup-tier-on-base) all match. **Nothing new** — the one sweep that came back completely clean.

## Not reached

Nothing was skipped. §3.9–§3.11, §4 and §5 were scanned in full against the code; §2.8's 68 rungs were walked individually against the gate sequence of all 30 state-driving endpoints; §2.9's 28 un-numbered gates were inventoried with their ladder positions; §2.10's four guards and §2.11's eleven invariants were each verified; F1–F13 were each independently re-verified against the code and all thirteen adjudications are correct as written.

**Orchestrator verification:** `PRD_COMPLETED.md` 1,001 lines / 251,080 chars vs `PRD_FINALIZED.md` 1,001 / 227,576 (+23,504 chars, 54 hunks). `find -newer results.8.json` over `implementation/`, `test_suite/` and `test_helpers/` returns nothing but sibling results files — **Steps 8 and 9 touched documentation only**; the 181/181 x8 green sweep still stands unmodified.

---

# PIPELINE COMPLETE — task_0951_vacation_home_snowbird_concierge

| Step | Outcome |
|---|---|
| 2 Scaffold | 23 ent / 18 SM / 53 calc / 73 val over 68 rungs / **142 ep** / 98 err / 8 roles / 105 constants / 10-gate order / 11 invariants / 3 OCC / 8-hop cascade — largest surface to date |
| 4 PRD | 978 lines, 13 declared open frictions (F1–F13) |
| 5 Tests | 182 tests (52 queue-A + 130 queue-B), 7 instances skipped, 13-entry near-miss register |
| 6 Impl | 5,385 lines / 22 modules, route diff 142/142 MISSING 0 EXTRA 0 |
| 7 Sweep | **181/181 x 8 rounds**; 1 deletion, 3 `test_suite/` fixes, **0 impl fixes**, 0 fairness flags |
| 8 Finalize | 74 hunks; all 13 frictions pinned; 10 generator claims refuted |
| 9 Complete | 54 hunks total; 17 further mismatch-revisions + 10 ambiguity-pins; 17 more claims refuted, 7 of them the PRD's own claims about itself |
