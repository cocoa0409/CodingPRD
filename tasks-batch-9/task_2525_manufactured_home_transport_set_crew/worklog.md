# Worklog — task_2525_manufactured_home_transport_set_crew

## Step 1: Create task directory — 2026-09-03T05:27:46.695Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2525_manufactured_home_transport_set_crew/` and `.../workspace/` (pre-assigned path; no index auto-allocation performed, per orchestration instructions).

## Step 2: Generate Scaffold — 2026-09-03T07:08:12.169Z

All three scaffold artifacts are complete and lint-clean.

## Output
`/home/ubuntu/github/CodingPRD/tasks/task_2525_manufactured_home_transport_set_crew/`
- `SCAFFOLD.yaml` — 3171 lines (§1.0–§1.7 + preamble; no `scaffold_difficulty_design` / `scaffold_corner_design` keys)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 1761 lines (single key `scaffold_difficulty_design`)
- `SCAFFOLD_CORNER_DESIGN.yaml` — 4616 lines (single key `scaffold_corner_design`)

Scenario text stored verbatim (verified byte-for-byte). `domain_name: manufactured-home-transport-set`, `api_prefix: /installations`, `difficulty_level: expert_plus`. No sibling task directory was read, listed, or grepped at any point.

## Counts
- §1.1 entities: **14**; §1.2 state machines: **9** (+ 2 `concurrency_rules`); §1.3 calculations: **12**; §1.4 validations: **30** (single priority ladder 1–30); §1.5 endpoints: **65**; §1.6 errors: **51**; §1.7 roles: **7** (`segregation_of_duties` role model, 3 entity-backed identities)
- §1.8: **9 difficulty rules × 2 instances = 18**, all with executed-literal asserts
- §1.9: **74 rows across all 9 taxonomy sections** — **49 full instances + 25 `excluded_because` stubs** (entities 12, state_machines 7+5, calculations 6+8, validations 4+4, endpoints 4+1, errors 8+4, rbac 4, cross_cutting 3+3, consistency_model 1)
- Audits: every one of the 51 error ids and all 65 endpoints appear in at least one §1.8/§1.9 call or probe; all 25 stub citations resolve to a real §1.8 `rule_id / instance` pair and no stub carries a `test_recipe`.

Final lint (`scaffold_lint.py`), verbatim:
```
Coverage
  §1.5 endpoints declared:    65
  §1.1 entities declared:     14
  §1.8 instances scanned:     18
  §1.9 instances scanned:     49
  Calls scanned (§1.8+§1.9):  962

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

## Design adjudications made while writing §1.9 (all fixed in SCAFFOLD.yaml)
1. **Pilot-car precondition had no error mapping** — `issue` required a RESERVED `PILOT_CAR` assignment but validation 26 only counted escort heads. Fixed across three places (validation 26 check/description, `ERR_PERMIT_ESCORT_SHORTFALL` condition, `issue` side effect).
2. **`ERR_CLAIM_STAGE_MISMATCH` was untriggerable** — every `discovered_stage` value was a `STAGE_OWNER` key. Added `UNKNOWN` to the enum plus a NOTE in `damage_claim_allocation.constants` (only the EVIDENCE basis can settle it).
3. Earlier fixes retained: validation 20 `SCOPE_SPLIT`→`SCOPE_DELIVERED`; validation 11 `license_expires_on`→`license_expiry_date`; validation 16 / `ERR_LEG_PERMIT_MISMATCH` respecified as leg `state_code` == permit `state_code`; undeclared payload keys stripped; one wrong `deviation_score` literal corrected.
4. **Three stubs cited §1.8 instances that do not exist** (a fabricated `hauler_suspension_threshold_boundary_at_exactly_500000`, plus mis-citations for `ERR_LEG_PERMIT_MISMATCH` and the two 412s — the lint does *not* validate stub citations). Replaced with a real instance (`hauler_suspension_at_exactly_the_threshold_then_leg_state_mismatch`: claimed 555556 → `round_half_up(500000.4)` = 500000 = threshold → SUSPENDED → 422, reverse → ACTIVE, then TX-leg-on-AZ-permit 422) and two real OCC instances.
5. **Lint forbids `as:` roles outside an endpoint's §1.5 `roles`, and requires all required `input:` fields present**, so negative RBAC probes (403/401) and malformed-body probes (400) cannot be structured calls. They are written as explicit prose `assert` lines ("the same request sent with X-User-Role … returns 403 ERR_UNAUTHORIZED"), with the structured `trigger` reserved for positive controls and 404/412 cases.
6. Traps documented rather than papered over: `pay-fee` exists only as `REQUESTED → FEE_PAID`, so a permit cannot be topped up and the fee-priority instance terminates at the 402; an 11-pier 2-section site can never be signed away, so that instance asserts `READINESS_FAILED` twice; a `SUPERSEDED` set job releases crew capacity, so the OCC supersession instance uses `daily_capacity: 2` to keep the second booking legal.

## Step 3: Copy Shared Files — 2026-09-03T07:08:12.169Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` → `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-03T07:21:54.987Z

PRD generated and verified.

**Output:** `workspace/PRD.md` — **427 lines / 95099 chars**
**Last heading:** `## 5. Error Code Catalogue` — file ends at a real section boundary, on the complete final table row `| ERR_CLAIM_STAGE_MISMATCH | 422 Unprocessable Entity |`. No mid-sentence truncation.

Orchestrator anti-truncation check (independent of subagent claim): `grep -n '^#'` returned 30 headings ending at §5 (line 373); `tail -25` shows the error table complete through its 51st row. VERDICT: not truncated, no regeneration needed.

Both hard constraints honored: `SCAFFOLD_DIFFICULTY_DESIGN.yaml` and `SCAFFOLD_CORNER_DESIGN.yaml` never opened, grepped, or referenced; no sibling `task_*/` read. PRD.md written across 8 chunked heredoc appends rather than one giant Write.

## Structure

**§1. Introduction** — 3 paragraphs framing the plant→corridor→site→set→certification→invoice lifecycle.

**§2. Global Specifications & System-Wide Principles** (11 subsections)
2.1 Operators, Roles and Trading-Partner Identity · 2.2 API Response Structure (byte-identical verbatim block, confirmed by string match against `section-2.2-response-structure.md`) · 2.3 Pagination and Collection Filters · 2.4 Resource Identity, Timestamps and Revision Counters · 2.5 Stale-Parent Rejection on Anchored Writes · 2.6 The Logical Clock · 2.7 Money, Minutes and Rounding Discipline · 2.8 Order Posture: the Derived Gate over an Order's Descendants · 2.9 Cascade Discipline, Version Propagation and Conserved Quantities · 2.10 The Validation Priority Ladder (all 30 priorities with error IDs, statuses, `applies_to` scopes) · 2.11 Path Resolution and Reference Integrity.

**§3. Business Logic & Workflows** (9 subsections, freely grouped by domain narrative)
3.1 Onboarding the Installation Network · 3.2 Opening an Order and Declaring the Home's Floors · 3.3 Preparing the Destination Site · 3.4 Permit Routing: Classing the Load, Sizing the Escort, Pricing the Move · 3.5 Corridor Legs, Escort Reservations and the Road · 3.6 Booking the Installer Crew and Dispatching the Set · 3.7 Setting the Home: Two Independent Dimensions · 3.8 Anchoring Certification, Final Inspection, Invoice and Warranty Start · 3.9 Damage-in-Transit Claims and the Chargeback Ledger.

**§4. Endpoint Definitions** — 65-row, 4-column table (Method | Path | Description | Authorized Role(s)); row count verified = 65.
**§5. Error Code Catalogue** — 51-row, 2-column table; row count verified = 51.

## Scaffold coverage

All 14 entities, 65 endpoints, 30 validations, 51 errors, 12 calculations, 9 state machines, 7 roles, and both OCC concurrency rules are represented.

## Hard Contract reports

**Contract 1 — Field-Name Coverage: PASS**
- `entities[].fields`: 109 required, 109 present, 0 missing
- `endpoints[].request_body`: 85 required, 85 present, 0 missing
- `endpoints[].query_params` + computed-read outputs: 30 required, 30 present, 0 missing
- All 51 error IDs, all 7 role names, and all state/enum tokens present (0 enum values missing)

**Contract 2 — Rule Coverage: PASS**
All 30 validation priorities carry their error ID, HTTP status and applies-to scope; both OCC rules (`expected_order_version` → `ERR_STALE_ORDER_VERSION` 412 on set-job creation; `expected_section_version` → `ERR_STALE_SECTION_VERSION` 412 on permit creation) state field, error and status; every state-machine transition appears with preconditions and side effects, including the parallel `progress_status` × `scope_status` dimensions, the cyclic anchoring re-submission loop with its 3-revision ceiling, the posture-driven order gate, and the `READINESS_FAILED → READINESS_FAILED` self-loop that deliberately does not re-derive posture; all 12 calculations are given in reconstruction-grade prose with pinned rounding order (per-joint-then-sum-then-round for the marriage-line score; discount as a percentage of the pre-discount invoice total with the tier never re-evaluated); sibling branches are symmetric for the four Site readiness outcomes, the two final-inspection branches, and the two claim-adjudication branches, including the EVIDENCE largest-remainder tie-break (fractional part DESC, points DESC, then `HAULER` < `INSTALLER` < `PLANT`).

**Contract 3 — §3 Path Purity: PASS**
732 backtick tokens scanned in §3: 0 tokens beginning with `/`, 0 bare HTTP-method tokens, 0 method+path combinations.

One late fix: the generator's own coverage script caught three constants rendered in words only. They now carry explicit numerals and codes — `0.25` inches maximum joint gap, `0.5` inches maximum offset, and per-state escort bases spelled out as `AZ` 0, `NM`/`TX`/`OK` 1, `KS`/`CO` 2 (with the `KS` pilot-car condition and the `KS`-or-`CO` destination rule). A vague reference to left-to-right FK resolution order was replaced with an explicit per-endpoint enumeration so priority 5 is reconstructable without guessing field order.

## Step 5: Generate Unit Tests — 2026-09-03T08:11:32.454480862Z

The test suite for task 2525 is complete and audited.

## Files written

`test_helpers/` — 2,696 lines across 9 files: `types.py` 448, `constants.py` 83, `api_errors.py` 135 (52 error ids + HTTP map registration), `api_client.py` 313, `test_users.py` 87, `factories.py` 310, `assertions.py` 334, `fixtures.py` 937 (primitives + 14 composite setups), `__init__.py` 49.

`test_suite/` — 10,837 lines across `conftest.py` (81) plus 27 test modules:

| queue A (41 tests) | | queue B (128 tests) | |
|---|---|---|---|
| test_01_permit_fee_provisional_and_final | 278/2 | test_20_entity_representations | 591/11 |
| test_02_damage_claim_allocation_bases | 235/3 | test_21_entity_listing_lookup_and_rejections | 504/11 |
| test_03_escort_matrix_combinatorics | 214/2 | test_22_transport_lifecycle_transitions | 466/8 |
| test_04_marriage_line_closure_scoring | 168/2 | test_23_set_and_claim_state_locks | 654/14 |
| test_05_anchor_certification_revision_cycle | 247/3 | test_24_installation_invoice_waterfall | 337/7 |
| test_06_set_job_independent_dimensions | 228/3 | test_25_fee_ledger_and_anchor_calculations | 501/8 |
| test_07_permit_revocation_cascade | 260/3 | test_26_permit_and_anchor_validations | 553/7 |
| test_08_chargeback_adjudication_cascade | 158/2 | test_27_endpoint_round_trips | 489/7 |
| test_09_dispatch_and_escort_priority_pairs | 352/4 | test_28_not_found_and_uniqueness_errors | 348/9 |
| test_10_permit_class_width_boundary | 228/3 | test_29_gate_ladders_and_thresholds | 1105/20 |
| test_11_zero_joint_marriage_line | 97/2 | test_30_role_authorisation | 1172/18 |
| test_12_cross_entity_state_gates | 276/4 | test_31_occ_and_ledger_threshold_layers | 477/6 |
| test_13_escort_and_crew_temporal_overlap | 281/4 | test_32_immediate_consistency | 212/2 |
| test_14_compensating_invariants | 352/4 | | |

**169 tests total — 41 queue A, 128 queue B.** One test is a 14-case parametrised not-found sweep.

## Audit result (machine-checked)

- All 18 difficulty instances have >=2 tests (2-3 each); all 49 non-stub corner instances have >=1 (1-7 each). Zero under-covered, zero missing.
- 169 tests, 169 `Design:` tags — exactly one per test, always the last docstring line, every tag resolving to a real `name:` in the source yaml. No tag points at an `excluded_because:` stub; all 20 stub `difficulty_instance:` cross-references resolve.
- Every docstring's quoted span was verified as a whitespace-normalised verbatim substring of `workspace/PRD.md`. No test lacks a quotation.
- No `skip`/`skipif`/`xfail`; no forbidden vocabulary (scaffold / Table N / §1.x / design index / test_recipe).
- `py_compile` clean on all 36 `.py` files; all 27 test modules import successfully against the real framework; no duplicate test function names.

## Instances skipped: none

All 67 non-stub instances survived the PRD-first filter. Nine individual `assert:` lines were dropped inside otherwise-emitted tests, with categories:

- **computed-field**: `updated_at` strictly later than `created_at` (PRD never says stored timestamps come from the logical clock vs wall time); `RouteLeg.version == 3` after a rejected call (replaced by a before/after equality check); `final_fee_cents is null` after a failed issuance (§3.4 overwrites before gating).
- **applies_to-scope**: the "already mated" arm of the section mate pointer (no row-level outcome is unanimous across the outgoing/incoming/symmetric readings); a foreign-plant *dispute* (dispute is not among priority 6's ten operations); the "no DELETE endpoint is declared" assertion (not API-observable).
- **error-precedence**: cross-rung masking in the dispatch gate (§2.10 priority 17 and §3.6 prose disagree on order) and in the final-inspection ladder — each rung isolated to a single violation instead. The scope-vs-crossover pair *is* asserted, being uniquely derivable.
- **default-value**: `Plant/Hauler/SetCrew status == ACTIVE` outside one instance's declared grounds; reliance on omitted evidence points defaulting to 0.
- **enum-write-pathway**: topping up an already-`FEE_PAID` permit (PRD never says `pay-fee` is legal out of `FEE_PAID`).

## Design-index defects adjudicated in favour of the PRD

1. `pad_type: "CONCRETE_RUNNER"` (~14 sites) and `"PIER_AND_BEAM"` (1 site) are outside §3.3's `SLAB | RUNNER | CROSSING_BEAM` -> all 10 surviving `pad_type` literals in the suite are `"RUNNER"`.
2. `set_job_parallel_dimensions_advance_independently` expects a utility crossover to succeed on a `SCHEDULED` job; §3.7 says it waits for dispatch. Not asserted — the instance is covered by its scope-split half, its post-dispatch crossover half, and the marriage-line close.
3. `permit_fee_provisional_vs_final_divergence` under-reserved escorts, making its own `status == ISSUED` unreachable through §3.4's sufficiency gate; a second conflict-free `ESCORT` reservation was added, leaving every fee/class/date literal intact.
4. Field-name fixes: yaml `HomeSection.status` -> `transit_status`; `RouteLeg.leg_status` -> `status` (0 `"leg_status"` references remain).
5. Two yaml expectations contradicted by §2.8/§3.3 were corrected: a fresh site's `blocking_defect_count` is `0` not null, and an unready site with no set job booked leaves the order `OPEN`, not `SITE_BLOCKED`.

One helper limitation worth noting for later phases: `setup_delivered_order` / `setup_order_with_ready_site` cannot take `order_overrides={"section_count": N}` (it collides with the explicit `section_count=` parameter), so declared-vs-recorded mismatch scenarios are built inline from primitives.

## Step 6: Generate Implementation — 2026-09-03T08:11:32.473916070Z

Implementation complete and verified.

## Files written — `workspace/implementation/`

| file | lines | contents |
|---|---|---|
| `start.sh` | 10 | `set -euo pipefail`, `cd $(dirname $0)`, **guarded** `pip install` (only when `import flask` fails), `exec python3 app.py` |
| `requirements.txt` | 1 | `flask>=2.0` |
| `app.py` | 77 | blueprint registration, `before_request` auth, `ApiError`/404/405/400/500 envelope handlers, `0.0.0.0:$PORT` (default 10000) |
| `errors.py` | 147 | `ApiError`, all 51 catalogue codes + HTTP statuses, default messages, `fail()`, `message_for()` |
| `store.py` | 178 | in-memory dicts (14 tables), logical clock at `2026-08-01T00:00:00Z`, `base_row`/`mark`/`public`/`sorted_rows` |
| `envelope.py` | 55 | `meta`/`response_type`/`data` envelope, `req_`+20-char request id, list `limit/offset/total_count/has_more` |
| `guards.py` | 259 | priorities 1-5: auth headers, role gate, typed body schema, path lookup, ref lookup, pagination + filters |
| `calc.py` | 302 | all 11 calculations, `Decimal`+`ROUND_HALF_UP`, floor+largest-remainder evidence split |
| `domain.py` | 519 | relationship walks, serializers, posture ladder, chargeback ledger + 5-level cascade, escort minute ledger, order summary |
| `routes_partners.py` | 245 | clock + plants/haulers/escort-crews/set-crews (13 endpoints) |
| `routes_orders.py` | 416 | orders/sections/sites incl. summary, measure, release, readiness-inspection (15) |
| `routes_transport.py` | 455 | permits/route-legs/escort-assignments (15) |
| `routes_set.py` | 493 | set-jobs, marriage-joints, anchor-certifications (17) |
| `routes_claims.py` | 316 | damage-claims incl. review/dispute/adjudicate/reverse (7) |

Total 3,473 lines. **65 endpoints registered** — exactly matching the PRD §4 table (verified by dumping `app.url_map`).

## Verification performed
- `python3 -m py_compile` clean on all 12 modules.
- Full happy-path end-to-end script (registration -> order -> sections measure/release -> site readiness -> 2 permits with fee/escort/pilot-car coverage -> issue -> depart/arrive -> delivery -> set job -> dispatch -> scope-split -> crossover -> marriage joint -> close line -> anchor cert with REQUEST_CHANGES + resubmit + CERTIFY -> final inspection PASS -> claim submit/review/dispute/review/adjudicate/reverse -> all 14 list endpoints): **0 failures**. Invoice landed at 724,010 cents, hand-checked against PRD §3.8 (pre-discount 891,500 -> 6% tier -> crossover waived -> 777,500 - 53,490). Evidence split of 81,001 on 1/1/1 points gave plant 27,000 / hauler 27,001 / installer 27,000 and reversal restored every balance to 0 (conserved total exact).
- Negative ladder suite (20 cases): missing/empty headers -> 401, bad role -> 403, body schema before path 404, path 404 before body-ref 404, pagination bounds, unrecognised filter enum, unknown path -> `ERR_NOT_FOUND`, wrong method -> `ERR_METHOD_NOT_ALLOWED`, malformed JSON -> `ERR_INVALID_REQUEST`: **all pass**.
- Fresh boot on a second port: all 14 collections return `total_count: 0` — no seeding anywhere (`grep` confirms no `seed`, no sqlite, no file I/O).

## PRD ambiguities resolved
1. **`created_at` clock** — real wall-clock, not the logical clock (PRD §2.6 enumerates exactly which rules read the logical clock); a hidden `_seq` gives stable `created_at ASC` ordering for ties.
2. **Version bumps** — `mark()` bumps a row at most once per request; the order's version rises on posture change plus the child-creation bumps PRD §2.9 declares explicitly.
3. **`SetCrew.status`** — derived on read from `license_expiry_date` vs the logical date (so moving the clock bumps no versions); the `status` list filter compares the derived value.
4. **Clock echo** — `POST /_clock/set_current_utc` returns the client's raw `current_utc` string, unnormalised.
5. **Permit issue ordering** — the four recomputed fields are persisted and the permit version bumped *before* the two gates, following the literal PRD sentence over the skill's generic atomicity advice.
6. **`pay-fee` gate** — `REQUESTED` only (SCAFFOLD precondition), so paying an already-`FEE_PAID` permit is `ERR_INVALID_STATE`.
7. **Route-leg window well-formedness** -> `ERR_INVALID_REQUEST` at priority 3, since `ERR_INVALID_WINDOW` is scoped to escort-assignments and set-jobs.
8. **Escort reservation** — leg-window bound checks folded into `ERR_INVALID_WINDOW` (priority 21), running after endorsement (12) and overbooked (13) and before conflict (22); `certified_roles` is not enforced (no error code exists), and no leg-state gate was invented.
9. **Escort release** — leg-owner check precedes the state gates, per §2.1 ("ownership is evaluated only after the addressed row is known to exist").
10. **Section-of-order mismatch on a claim** -> `ERR_SECTION_NOT_FOUND` (the floor is not a floor of that order).
11. **Ownership deliberately not enforced** on section create/patch, order create, claim create, escort-assignment create — PRD enumerates exactly ten priority-6 operations.
12. **Uniqueness of `hud_plant_code`/`dot_number`/`hud_installer_license_no` not enforced** — the error catalogue contains no code for it.
13. **`set_crew_day_load`** evaluated only at probe points (candidate start + overlapping job starts in range) rather than iterating the whole date range.
14. **Evidence-points defaults** — absent optional points default to 0.
15. **Band-1 vacuous CLOSED** (all set jobs `SUPERSEDED`) implemented literally, though unreachable since superseding requires a new `SCHEDULED` job.

## Step 7: Run Tests and Iterate — 2026-09-03T08:42:55.853777344Z

All 8 rounds green. Exit condition met.

## Summary

**Iterations run: 2**

**Iteration 1 sweep:** 8/8 rounds at 180/182 — union of exactly 2 failures, each failing in every round (deterministic, no flakiness or load-induced noise). Both diagnosed to STEP 2 (test bugs); no implementation change and no deletion warranted.

**Iteration 2 sweep:** 8/8 rounds at **182/182 passed, 0 failed, 0 errors, 0 skipped** (durations ~350s; `Terminated` count in sweep.log = 0, so no reaping artifact).

### Tests deleted
None. Both union failures survived STEP 1a and STEP 1b — each asserted rule is verbatim in PRD.md and uniquely determined.

### test_helpers/ fixes
None. Neither failure traced to `test_helpers/`; both were local to a test module.

### test_suite/ fixes
1. `test_suite/test_29_gate_ladders_and_thresholds.py` — added `validate_paginated` to the `from test_helpers import (...)` block. `test_a_suspended_carrier_cannot_be_booked_onto_a_new_corridor_leg` called it at line 1005 for its "the refused booking wrote no leg" check but never imported it, so the test died with `NameError` after its already-correct `ERR_HAULER_SUSPENDED` 422 assertion (PRD §3.5 and §2.10 priority 14). Assertion strength unchanged — the fix lets a previously unreachable assertion actually run.
2. `test_suite/test_30_role_authorisation.py` — removed the `measure_and_release_section(section["id"], plant["id"])` line from `_ladder_world()` (docstring updated to state the floor is deliberately left `AT_PLANT`). The fixture drove the floor to `PERMIT_PENDING`, but `test_an_unresolvable_path_id_reports_the_addressed_entitys_own_404_code` uses `measure` as its positive control, and PRD §3.2 permits plant QC only "on a floor that is `AT_PLANT`" — so the PRD-faithful implementation correctly returned `ERR_INVALID_STATE` and the test failed with "Expected 200, got 409". Verified safe for the helper's other four call sites: three issue only 401/403/400 negative probes plus one section read, and the fourth requests a permit, for which PRD states no transit-status gate. `measure_and_release_section` is still imported and used at lines 75 and 442.

### implementation/ fixes
None. No implementation file was modified in either iteration; storage remains in-memory only with no startup seeding.

### Non-blocking observations (no test asserts them, so left alone)
- PRD §3.1 declares `hud_plant_code`, `dot_number` and `hud_installer_license_no` unique, but §5 defines no error id for a collision and `routes_partners.py` does not enforce it — not uniquely derivable, so nothing added.
- `create_route_leg` treats `window_end <= window_start` as a priority-3 `ERR_INVALID_REQUEST`; defensible because §2.10 priority 21 scopes `ERR_INVALID_WINDOW` to escort-assignments and set-jobs only.
- `dispute_claim` checks `ERR_NOT_RESOURCE_OWNER` before its state check, although dispute is not one of the ten priority-6 operations; no test probes that pair.

### Orchestrator verification (independent of subagent claim)
Re-read all 8 `results.*.json` directly: every file reports `passed == total == 182`. `grep -c Terminated workspace/sweep.log` = 0, confirming no SIGTERM reaping artifact (sweep was run under `setsid nohup`).

### Step 8 gate
Step 7 ran 2 iterations with 2 `test_suite/` fixes, so the Step 8 skip condition (zero iterations beyond baseline) does NOT apply. Step 8 will run. Note that Step 7 applied 0 `implementation/` fixes, so the `<step_7_diff>` handed to Step 8 consists solely of the two test_suite fixes — both of which are candidate PRD-silence sites rather than impl mismatches.

## Step 8: Finalize PRD — 2026-09-03T08:46:52.441943221Z

PRD_FINALIZED.md produced.

## Line counts
- `PRD.md`: 427 lines; `PRD_FINALIZED.md`: 427 lines (0.00% line-count delta).
- 5 lines modified out of 427 = **1.17% of lines touched**; no lines added or removed, no new sections.

## Changes (one bullet each)

- **§3.1 (plant paragraph)** — revise — `hud_plant_code` "must be unique across all plants" -> "expected to be unique … a data expectation rather than a constraint the registration endpoint enforces, since §5 defines no error id for a collision and a repeated code is accepted like any other string" — `routes_partners.py:44-63`
- **§3.1 (hauler paragraph)** — revise — `dot_number` "(unique across all haulers)" -> "(expected unique across all haulers, and likewise not enforced at registration)" — `routes_partners.py:86-107`
- **§3.1 (installer-crew paragraph)** — revise — `hud_installer_license_no` "must be unique" -> "expected to be unique … (again not enforced at registration)" — `routes_partners.py:199-227`
- **§3.5 (corridor-leg paragraph)** — insert — one sentence pinning that an ill-ordered leg window is a priority-3 `ERR_INVALID_REQUEST` (400), evaluated before any body reference is resolved, and that `ERR_INVALID_WINDOW` stays scoped to escort reservations and set jobs — `routes_transport.py:226-227` (check precedes `lookup_ref` at 229-230)
- **§2.10 priority 6** — revise + insert — "guards exactly ten operations" -> "as stated guards ten operations", plus a clause naming two further operations whose own ownership condition is evaluated in the same position, ahead of the priority-7 state gate: escort-reservation release and damage-claim dispute — `routes_claims.py:205-218`, `routes_transport.py:443-449`

## Per-edit pre-edit search log

**Edit 1-3 (subject: uniqueness of partner business identifiers)**
- (a) Subject: enforcement of `hud_plant_code` / `dot_number` / `hud_installer_license_no` uniqueness, and any error surface for a collision.
- (b) Enumerated: `grep -rn "hud_plant_code|dot_number|hud_installer_license_no" implementation/*.py` -> only the three `validate` specs and the three row writes in `routes_partners.py` (49/57, 90/99, 203/219); no scan of existing rows anywhere. `errors.py` grepped for `DUPLICATE|UNIQUE|CONFLICT` -> only the four scoped-uniqueness codes (section index, leg sequence, joint index, anchor cert); no partner-identifier code exists. Also checked the three list endpoints (`list_plants`, `list_haulers`, `list_set_crews`) — they filter on `status`/`state_code` only, so no read path depends on uniqueness.
- (c) Adjustment: kept the uniqueness *expectation* in the prose rather than deleting it (the fields are still required non-empty strings), and scoped the non-enforcement statement to "at registration" so it does not claim anything about any other endpoint.

**Edit 4 (subject: interval well-formedness on a corridor leg)**
- (a) Subject: where a `window_end <= window_start` violation lands, per entity, and its rank.
- (b) Enumerated every window/interval check in the impl: `create_route_leg` (`routes_transport.py:226`, `ERR_INVALID_REQUEST`, before `lookup_ref` of permit/hauler at 229-230); `create_escort_assignment` (`routes_transport.py:394`, `ERR_INVALID_WINDOW`, after endorsement 385 and overbooked 387, before conflict 396 — and it also covers leg-containment `start < leg_start or end > leg_end`); `create_set_job` (`routes_set.py:54`, `ERR_INVALID_WINDOW` for `end_day < start_day`, after posture/version, before capacity). Also checked `guards.py:_check_one` "datetime" — parse-only, no cross-field logic.
- (c) Adjustment: worded the new sentence to talk **only** about the leg, and described `ERR_INVALID_WINDOW`'s scope as "escort reservations and set jobs" without enumerating *which* escort-window violations it covers — deliberately leaving the reservation's leg-containment arm undisturbed, since narrowing it to "end after start" would have mis-described `routes_transport.py:394`.

**Edit 5 (subject: position of ownership checks relative to the state gate)**
- (a) Subject: every ownership/`ERR_NOT_RESOURCE_OWNER` check in the impl and its rank versus priority 7.
- (b) Enumerated via `grep -n "ERR_NOT_RESOURCE_OWNER|actor_id()" implementation/*.py` and read each site: the ten PRD-listed ops all check owner before state — `measure` (`routes_orders.py:297` vs 298), `release` (312 vs 313), `depart` (`routes_transport.py:288` vs 291), `arrive` (319 vs 321), `scope-split` (`routes_set.py:173` vs 174), `utility-crossover` (199 vs 200), `close-marriage-line` (217 vs 218), `marriage-joints` (322), `anchor-certifications` (386 vs 388/390), `resubmit` (478 vs 480). Two unlisted ops do the same: `release_escort_assignment` (`routes_transport.py:444` vs 446/448) and `dispute_claim` (`routes_claims.py:214` vs 217). Also confirmed the *negative* cases so the wording stays true: `amend_section` (`routes_orders.py:202-247`) has **no** ownership check at all, and the inspector-identity checks (`routes_set.py:258`, `routes_orders.py:411`, `routes_set.py:460`) are `ERR_SEGREGATION_OF_DUTIES` / recording, not ownership.
- (c) Adjustment: replaced the intended universal ("any operation with an ownership condition is evaluated at priority 6") with an explicit two-item enumeration naming only escort-release and dispute, because a universal would have falsely implied `PATCH /installations/sections/{id}` carries an ownership gate. Also softened "guards exactly ten" to "as stated guards ten" rather than restating a new exact count.

## Items judged to need no edit
- **test_suite fix 1** (missing `validate_paginated` import in `test_29`): pure test bug. The asserted rule — `ERR_HAULER_SUSPENDED` 422 when booking a leg onto a suspended carrier — is verbatim in PRD §3.5 / priority 14 and matches `routes_transport.py:231-232`.
- **test_suite fix 2** (`_ladder_world()` fixture drove the floor to `PERMIT_PENDING`): pure fixture bug. PRD §3.2 already pins plant QC to a floor that is `AT_PLANT`, and `routes_orders.py:298` matches. Separately verified the helper's permit-request call site needs nothing: `create_permit` (`routes_transport.py:31-85`) applies **no** transit-status gate, and PRD §3.4 states none — so PRD and impl already agree and no sentence was added.

## Step 9: Complete PRD — 2026-09-03T09:11:58.234484661Z

Step 9 was executed as **three sequential file-partitioned passes** over the 3,473-line implementation rather than a single subagent scan. Orchestrator rationale: a 12-module / 65-endpoint implementation does not fit a faithful one-pass walk, and the known failure mode is a subagent reporting a completed scan while leaving `PRD_COMPLETED.md` byte-identical to its source. Partitioning forces each pass to actually read its files. Pass 1 performed the `cp`; passes 2 and 3 edited the existing file in place with targeted `Edit` calls, and each pass was handed the prior passes' "already-pinned, do not re-flag" list to prevent churn and re-litigation.

**Source vs output:** `PRD_FINALIZED.md` 427 lines / 96,396 chars -> `PRD_COMPLETED.md` 427 lines / **106,660 chars (+10,264 chars)**. No lines added or removed — every edit is an in-paragraph insert or revision, so no section was displaced. 37 lines modified (74 diff lines).

**Totals across the three passes: 44 edits — 35 ambiguity-pins, 9 mismatch-revisions.**

### Pass 1 — app.py, errors.py, store.py, envelope.py, guards.py, calc.py, routes_partners.py (9 pins, 3 mismatches)
- §2.1 — revise — ambiguity — whitespace-only `X-User-ID`/`X-User-Role` counts as empty for `ERR_UNAUTHENTICATED` — `guards.py:36-39`
- §2.2 — revise — ambiguity — `api_request_id` is `req_` + exactly twenty uppercase-alphanumeric chars; `api_request_timestamp` from real server time, not the logical clock — `store.py:78-80, 69-71`
- §2.3 — insert — ambiguity — empty `limit`/`offset` = omitted; non-integer or out-of-bounds = `ERR_INVALID_REQUEST` 400; `created_at` ties broken by insertion sequence — `guards.py:200-217`, `store.py:169-171`
- §2.3 — insert — ambiguity — filters match by exact string equality against the value the resource *reports* (so the set-crew `status` filter tests the computed status); empty-string filters and undeclared query params ignored — `guards.py:220-240`, `routes_partners.py:240-245`
- §2.4 — insert — ambiguity — `created_at`/`updated_at` stamped from real server time, not the logical clock — `store.py:130-156`
- §2.6 — revise — **mismatch** — the date-sensitive-rule list was wrong: only three rules read the logical clock (licence expiry, permit `valid_until_date`, `warranty_start_date`); hauler `insurance_expiry_date` is never evaluated and day capacity compares job dates only to each other — `domain.py:98`, `routes_transport.py:150-151`, `routes_set.py:277`, `domain.py:439-470`
- §2.6 — insert — ambiguity — the clock may move backwards; response `data` carries only `current_utc`, echoed verbatim — `routes_partners.py:30-36`
- §2.9 — insert — ambiguity — a row's `version` rises by exactly 1 per request however many effects touch it (`mark()` idempotent per request) — `store.py:141-156`
- §2.10 p3 — insert — ambiguity — undeclared body fields ignored; explicit `null` on an optional field = absent (sole nullable exception: the floor amendment's `mates_to_section_id`); required field sent `null` fails as missing; unparseable/non-object body always fails, absent body only where a field is required; free-text strings unbounded (empty string accepted); instants accepted with `Z`, a numeric offset, or no designator and normalised to UTC; numeric bounds inclusive both ends — `guards.py:150-188`, `store.py:18-50`, `routes_orders.py:222-227`
- §3.1 — insert — **mismatch** — hauler `insurance_expiry_date` and `endorsed_states` are recorded, not enforced — `routes_partners.py:91-101`
- §3.1 — insert — **mismatch** — escort crew `endorsed_states` and `certified_roles` recorded, not enforced; only `endorsement_class` tested at reservation — `routes_partners.py:134-167`, `domain.py:101-103`
- §3.4 — revise — ambiguity — an issuing state outside the six-state base table contributes 0 escorts (`state_code` validated only as two uppercase letters) — `calc.py:11, 96`

### Pass 2 — domain.py, routes_orders.py, routes_transport.py (13 pins, 6 mismatches)
- §2.8 — insert — ambiguity — posture re-derivation is a write (and `version` bump) only when the band actually changes — `domain.py:210-216`
- §2.9 — revise — **mismatch** — "parents whose derived posture was recomputed" always bump -> only when the band moved; partners bump when balance *or status* moves — `domain.py:214, 293/318`
- §2.10 p5 — revise — **mismatch** — body-reference resolution also applies to `PATCH /installations/sections/{id}`, ahead of its state gate — `routes_orders.py:231-239`
- §2.10 p26 — revise — **mismatch** — "non-cancelled legs" -> legs in `SCHEDULED`/`IN_TRANSIT` (excludes `ARRIVED`/`HAULER_HOLD`) — `domain.py:412-426`
- §2.11 — insert — ambiguity — roll-up `site_readiness_status` is null when the order has no site row — `domain.py:514`
- §3.2 — insert — ambiguity — `declared_length_in`/`declared_weight_lb` unbounded and never evaluated by any rule — `routes_orders.py:165-166`
- §3.2 — insert — ambiguity — the "third floor" mate test looks both directions (mate's own pointer; any third floor pointing at the mate), and the pointer is one-directional — no reciprocal write — `routes_orders.py:109-134`
- §3.2 — revise — **mismatch** — "amended by the same dispatcher" -> recording *and* amending a floor are not owner-scoped; `ERR_NOT_RESOURCE_OWNER` only on measure/release — `routes_orders.py:137-247`
- §3.2 — insert — ambiguity — `measured_width_in`/`measured_height_in` required but carry no bounds (may fall outside the declared envelope) — `routes_orders.py:292-294`
- §3.3 — insert — ambiguity — a second site row per order is accepted; every "the order's site" rule reads the earliest-created site — `domain.py:16-18`, `routes_orders.py:324`
- §3.4 — insert — ambiguity — permit request does not gate the floor's `transit_status` — `routes_transport.py:47-84`
- §3.4 — insert — ambiguity — only a `REQUESTED` permit may be remitted against (`ERR_INVALID_STATE` otherwise, so no top-up after `FEE_PAID`); `amount_cents` unbounded — `routes_transport.py:112-121`
- §3.4 — insert — ambiguity — a refused issuance is not unwound: the four recomputed fields and the bumped `version` persist with `status` still `FEE_PAID` — `routes_transport.py:132-147`
- §3.4 — insert — ambiguity — `valid_until_date` recorded, never compared to the clock; a floor in any status other than `PERMIT_PENDING`/`PERMIT_REVOKED_HOLD` is left untouched and issuance still succeeds — `routes_transport.py:150-156`
- §3.5 — insert — ambiguity — a leg may be added to a permit in any status — `routes_transport.py:229-254`
- §3.5 — insert — ambiguity — leg/reservation window strings stored and echoed verbatim; parsing to UTC is for comparison only — `store.py:25-50`, `routes_transport.py:246-247`
- §3.5 — revise — **mismatch** — reservations are booked by *a* `TransportManager` (not owner-scoped, unlike release), and the leg's status is not gated — `routes_transport.py:361-397`
- §3.5 — revise — **mismatch** — window well-formedness/containment is a fourth check (`ERR_INVALID_WINDOW`) after endorsement and crew status, before the conflict test ("Three checks" -> "Four checks") — `routes_transport.py:385-397`
- §3.5 — insert — ambiguity — depart's five conditions run in ladder order (ownership -> leg status -> permit status as `ERR_INVALID_STATE` -> escort crews -> carrier) — `routes_transport.py:287-303`

### Pass 3 — routes_set.py, routes_claims.py (13 pins, 0 mismatches)
Nothing in `routes_set.py` / `routes_claims.py` actively contradicted the PRD; every finding was PRD silence.
- §2.3 — insert — ambiguity — the filter enumeration omitted anchoring certifications entirely; pinned `set_job_id` and `status` — `routes_set.py:424-429`
- §2.10 p9 — insert — ambiguity — `POST /installations/set-jobs` carries the same code at this rung (against the `CLOSED` band alone, not `TRANSPORT_BLOCKED`) ahead of the stale-version gate at p10; dispatch adds the `CLOSED` arm — `routes_set.py:47-50, 133-134`
- §2.10 p17 — insert — ambiguity — impl tests the count first, so a dispatch failing both arms reports `ERR_SECTION_COUNT_MISMATCH` — `routes_set.py:138-143`
- §3.6 — insert — ambiguity — fresh set-job field values (`progress_status`/`scope_status` openers, four fee/count fields at 0, `crossover_recorded` false, `invoice_total_cents` and `final_inspector_user_id` null) — `routes_set.py:59-82`
- §3.6 — insert — ambiguity — the per-day census runs *before* the same-order supersession is written, so a still-`SCHEDULED` job of this very order counts against capacity — `routes_set.py:56` vs `83-86`
- §3.7 — insert — ambiguity — `skirting_linear_ft`/`steps_count` required with no bound (negatives accepted), and neither raw figure appears in the set job's representation (`_`-prefixed keys stripped by `public()`) — `routes_set.py:168-169, 181-182`, `store.py:159-166`
- §3.7 — insert — ambiguity — `crossover_count` must be zero or greater — `routes_set.py:196`
- §3.7 — insert — ambiguity — neither of the parent job's status dimensions gates joint recording; ownership and index uniqueness are the only gates — `routes_set.py:321-325`
- §3.8 — insert — ambiguity — `pier_count` recorded but never read by either verdict (contrast the site's own `pier_count`); the licence test is settled ahead of the duplicate test; no job status dimension gates submission — `routes_set.py:385-392`, `calc.py:281-294`
- §3.8 — insert — ambiguity — `punch_item_count` must be zero or greater — `routes_set.py:241-247`
- §3.9 — insert — ambiguity — a `section_id` belonging to another order is reported as `ERR_SECTION_NOT_FOUND` at the `section_id` resolution position, before `hauler_id`/`set_crew_id` resolve at all — `routes_claims.py:84-89`
- §3.9 — insert — ambiguity — `IN_TRANSIT`/`DELIVERED` are the only source states; submission gated by neither posture nor transit status, and a blocking claim on a floor in any other status still creates the claim while leaving floor, order `version` and posture untouched (as does any `blocks_set` false claim) — `routes_claims.py:121-126`
- §3.9 — insert — ambiguity — the three evidence-point fields are independently optional (supplied overwrites, omitted or explicit `null` retains), and the review/dispute cycle is unbounded, unlike §3.8's revision ceiling — `routes_claims.py:220-228`

### Orchestrator verification of Step 9 output
- `cmp PRD_FINALIZED.md PRD_COMPLETED.md` -> differs (the byte-identical no-op failure mode did NOT occur). 74 diff lines / 37 modified lines / +10,264 chars.
- All §1–§5 headings present; endpoint table still 65 rows; error catalogue still 51 rows; file ends on the complete final row `| ERR_CLAIM_STAGE_MISMATCH | 422 Unprocessable Entity |`. No truncation.
- Final green sweep re-verified after Step 9: all 8 `results.*.json` report `passed == total == 182`, `failed == 0`. Step 9 edits documentation only — no implementation or test file was touched — so the sweep result stands.

## PIPELINE COMPLETE — Step 9 wrote workspace/PRD_COMPLETED.md.
