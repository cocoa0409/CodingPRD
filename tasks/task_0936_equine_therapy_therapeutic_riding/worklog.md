# task_0936_equine_therapy_therapeutic_riding — worklog

Scenario (verbatim from user):
> 936. Equine Therapy & Therapeutic Riding (PATH): rider intake & assessment, horse-rider match & session, volunteer (leader/sidewalker) scheduling, instructor certification, scholarship/grant & billing, progress & goal, safety/incident, program reporting

Difficulty: **beyond-Expert** ("generate task hard than expert level!").

## Step 1: Create task directory — 2026-08-08T17:16:30.000Z

Created `tasks/task_0936_equine_therapy_therapeutic_riding/` and `workspace/`. Index 0936 = highest existing (0935) + 1.

## Step 2: Generate scaffold — 2026-08-08T18:11:00.000Z

All three artifacts are written, YAML-valid, and lint-clean.

**Files** (all under `/home/ubuntu/github/CodingPRD/tasks/task_0936_equine_therapy_therapeutic_riding/`):
- `SCAFFOLD.yaml` (3692 lines) — §1.0–§1.7 plus `datetime_conventions`, `constants`, `gate_precedence`, `conservation_invariants`, `cascades`. Neither design key present.
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (1651 lines) — single key `scaffold_difficulty_design`.
- `SCAFFOLD_CORNER_DESIGN.yaml` (3747 lines) — single key `scaffold_corner_design`.

## Counts

| Dimension | Value |
|---|---|
| Entities | **18** |
| Endpoints | **75** |
| Error codes | **40** |
| Ladder rungs | **44** (one ordered list, spanning all endpoints) |
| Status axes / state machines | **17** on 13 entities |
| Calculations | **29**, of which **7 dual-variant** |
| OCC rules | **3** |
| Conservation invariants | **5** |
| Max cascade depth | **5** (`charge_reversal_cascade`); second cascade depth 4 |
| §1.8 | 9 rule_ids × 2 instances = **18** |
| §1.9 | **9 sections, 78 instances** (69 with full recipes + 9 `excluded_because` stubs) |

**Non-linear axes (13):** `Rider.status` (ACTIVE↔MEDICAL_HOLD cycle), `Rider.assessment_status` (parallel axis on the same row, CURRENT→DUE→OVERDUE→CURRENT), `Session.schedule_status` (CONFIRMED→CREW_PENDING revert on crew release), `Session.billing_status` (parallel axis, compound over Charges), `Goal.status` (ACTIVE↔MET and ACTIVE↔STALE), `Horse.status` (3 hold branches back to AVAILABLE), `Volunteer.status`, `VolunteerQualification.status`, `Instructor.certification_status` (CURRENT→GRACE→LAPSED→CURRENT + suspension overlay), `Grant.status` / `ScholarshipAward.status` (EXHAUSTED↔OPEN restored by reversal), `MedicalRelease.status` and `ProgressNote.status` (branching).

**Dual-variant calcs (7):** `effective_load_lb` (current_declared / at_assessment), `session_fee_cents` (quoted 9000 / billed 6750), `medical_release_validity_at_instant` (at_booking / at_ride), `instructor_certification_status_at_instant` (at_booking / at_ride), `horse_workload_minutes` (committed / delivered), `volunteer_service_hours` (scheduled 2.0 / delivered 0.75), `period_report_aggregation` (draft_live_recompute / finalized_snapshot_plus_amendments).

## Declared constants + residual ALL_CAPS

**92** declared constant / table-key identifiers. Residual ALL_CAPS tokens = 97, all classified:
- 6 test-fixture data values (`CP_MILD_ASD`, `CP_SPASTIC`, `CP_ATLANTOAXIAL`, `CP_ORPHAN` created via `POST /condition-policies`; `BAND_Z`, `BANANA` are deliberate bad input);
- 11 format/protocol tokens (`YYYY`, `ISO8601`, `ASC`, `HTTP`, `ERR_XXX`, …);
- 80 English prose emphasis words (GROSS, REMAINING, PINNED, …) — not identifiers.

Every literal reason string (`INCIDENT_REST_HOLD`, `MANUAL`, `SESSION_CANCELLED`, `INCIDENT_SEV_1/2`, the open-ended suspension instant) is pinned in a new `LITERAL_REASON_STRINGS` block; input-only enum sets are pinned in `CANCELLATION_REASON_INPUT_MEMBERS`, `HOLD_TYPE_MEMBERS_BY_ENDPOINT`, `VARIANT_MEMBERS_BY_ENDPOINT` + defaults. Every unit conversion/mapping is an explicit table: `MINUTES_PER_HOUR`, `MAX_HORSE_LOAD_FRACTION`, `SLIDING_SCALE_PCT`, `INSTRUCTOR_TIER_ORDINAL`, `INDEPENDENCE_LEVEL_BANDS`, `INDEPENDENCE_CREW_MATRIX`, `INCIDENT_SEVERITY_MATRIX`, `INCIDENT_HOLD_MATRIX`, `FUNDING_SOURCES_BY_CHARGE_TYPE`.

## yaml.safe_load results

```
SCAFFOLD.yaml               → OK
SCAFFOLD_DIFFICULTY_DESIGN.yaml → OK
SCAFFOLD_CORNER_DESIGN.yaml     → OK
```

Offenders found and fixed during authoring: unquoted `$.data[0].id` JSONPaths inside flow mappings (the `[` broke the parser) and `grounds: [errors[ERR_X], endpoints."POST /x"]` flow lists — both now fully quoted.

## scaffold_lint.py verdict (verbatim)

```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           SCAFFOLD.yaml
  Difficulty design:  SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    75
  §1.1 entities declared:     18
  §1.8 instances scanned:     18
  §1.9 instances scanned:     69
  Calls scanned (§1.8+§1.9):  1001

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

All 40 error codes are referenced by at least one design instance (verified programmatically: zero unmentioned).

## gate_precedence order

1. `incident_hold_gate` (rung 14, ERR_INCIDENT_HOLD_ACTIVE)
2. `finalized_period_gate` (rung 15, ERR_REPORT_FINALIZED)
3. `horse_operational_hold_gate` (rung 16, ERR_HORSE_ON_HOLD)
4. `instructor_certification_gate` (rung 17, ERR_INSTRUCTOR_CERT_LAPSED)
5. `medical_release_gate` (rung 18, ERR_RELEASE_MISSING / ERR_RELEASE_EXPIRED)

Each carries an `observable_with_all_earlier_passing` clause naming the concrete setup that reaches it; §1.9 has a full recipe for each.

## Reachability self-repairs made

1. **Dropped `Horse.hold_incident_id`** (FK → Incident) and replaced it with a declared literal `hold_reason` string — the FK demanded a reverse-reachability GET on a horse list endpoint that had been trimmed.
2. **Added `medical_hold_incident_id?` and `active_release_id?` filters to `GET /riders`** so the two Rider back-pointer FKs pass check (f).
3. **`ERR_VOLUNTEER_SUSPENDED` was unreachable through its SUSPENDED limb** — gate 1 pre-empts every incident-placed suspension. Re-grounded the observable path on the INACTIVE (retraining-overdue) limb and documented the precedence in the error catalog.
4. **`ERR_REASSESSMENT_OVERDUE` and `ERR_RELEASE_EXPIRED` shared identical 365-day clocks** and would always fire together. Made each independently observable by allowing a fresh release (or fresh reassessment) to be filed on its own clock; both directions have full §1.9 recipes.
5. **`ERR_GRANT_RESTRICTION_VIOLATION` had no trigger** — the automatic candidate filter silently skips ineligible grants. Added optional `preferred_grant_id` to `POST /sessions/{id}/complete` as the explicit request the server must refuse.
6. **`ERR_FUNDS_EXHAUSTED` was unreachable** — private pay always absorbs the remainder. Added `Rider.funding_mode: FUNDED_ONLY`, scoped to SESSION_FEE only so cancellation fees can never deadlock.
7. **Deleted `ERR_SCHOLARSHIP_NOT_APPLICABLE`** (the skip is silent, never an error); its observability moved to the computed `Charge.scholarship_excluded` flag.
8. **Arithmetic feasibility retune of the horse ledger**: original weekly 480 / daily 150 / 4-per-day could not reach the weekly cap without 4+ setup days. Retuned to **240 / 150 / 3**, which is reachable in exactly 3 sessions (90+60 Monday, 90 Tuesday = 240) and crossable with one more — verified against `SESSION_MIN/MAX_DURATION_MINUTES` and the 15-minute rest buffer.
9. **`Session.billing_status = CHARGED` was a dead enum value** — pinned `Charge.status = FUNDED iff balance_due_cents == 0`, which makes CHARGED observable for any rider with a private-pay remainder.
10. **Enum-closure repairs**: removed `Horse.RETIRED`, `Grant.CLOSED`, `ScholarshipAward.REVOKED` after trimming their producing endpoints.
11. **Removed instructor-suspend / volunteer-reinstate endpoints**; SUSPENDED is produced by the incident cascade and cleared at incident close, so every enum member still has a declared producer.
12. **`ANKLE_HOLD` deliberately retained** as an enum member `INDEPENDENCE_CREW_MATRIX` never produces, so `ERR_HOLD_TYPE_MISMATCH` can be provoked with an enum-*valid* value instead of colliding with `ERR_INVALID_ENUM` (documented in the calc note).
13. **OCC chain repair**: `POST /sessions/{id}/crew-assignments` returns a CrewAssignment, whose `version` is not the session's — inserted `GET /sessions/{session_id}` refresh calls into every multi-crew chain so each `expected_session_version` traces to a real capture.
14. **Rider clearance path split**: incident close clears `medical_hold_incident_id` but leaves the rider MEDICAL_HOLD, so both the close transition and the `medical-clearance` transition are individually observable (§1.9 asserts the intermediate state).

## Domain seams used

| # | Seam | Became |
|---|---|---|
| 1 | Precaution vs contraindication split | `ConditionPolicy` entity keyed on (condition_code, activity_type); `precaution_tier_evaluation`; rungs 22–24; §1.9 `one_condition_code_is_a_precaution_for_riding_and_a_contraindication_for_vaulting` |
| 2 | Release expiry vs reassessment clock | `medical_release_validity_at_instant` (dual-variant at_booking/at_ride) + `assessment_status_derivation`; rungs 18 & 21; the two mirror-image §1.9 instances |
| 3 | Rider-weight ↔ horse capacity | `horse_max_load_lb` + `effective_load_lb` (dual-variant, `BACKRIDER_WEIGHT_LB`); rung 27, **inclusive** boundary; §1.8 `effective_load_exactly_equal_to_max_load_is_admitted` |
| 4 | Horse work-load ledger | `horse_workload_minutes` (dual-variant) + `horse_capacity_gates` + `horse_rest_interval`; rungs 29–31; invariant `horse_capacity_conservation` |
| 5 | Independence level drives crew | `INDEPENDENCE_CREW_MATRIX`, `crew_satisfaction_evaluation`, rungs 33/39/40; the **reversible** Session CONFIRMED→CREW_PENDING edge (§1.8 rule 3) |
| 6 | Volunteer qualification matrix | `VolunteerQualification` entity (per-role, per-age, annual re-training, suspension overlay); rungs 36–38; §1.9 `sidewalker_qualification_does_not_authorise_leading`, `fifteen_year_old_cannot_lead_but_may_sidewalk` |
| 7 | Instructor certification tiers & scope | `INSTRUCTOR_TIER_ORDINAL`, self-referential `supervisor_instructor_id`, `instructor_certification_status_at_instant` (dual-variant), gate 4, rungs 25/26/43; §1.9 grace-window instance |
| 8 | Funding waterfall with restricted money | `funding_waterfall_allocation` (modes a + c), `grant_candidate_selection`, `FundingAllocation`; invariants `grant_balance_partition`, `charge_money_conservation`, `scholarship_award_partition` |
| 9 | Cancellation / no-show fee vs funding | `cancellation_reason_derivation` + `cancellation_fee_cents` + `FUNDING_SOURCES_BY_CHARGE_TYPE`; §1.9 `no_show_fee_costs_more_out_of_pocket_than_the_session_it_replaced` (900 vs 3600 on identical 9000-cent gross) |
| 10 | Goals / progress with reassessment clock | `Goal` cyclic machine, `goal_progress_evaluation`, `goal_staleness_evaluation` via the `POST /_ops/goal-staleness-sweep` checkpoint — **explicitly monotone** (ACTIVE→STALE only; STALE→ACTIVE requires a rating) |
| 11 | Incident severity ladder with holds | `INCIDENT_SEVERITY_MATRIX` + `INCIDENT_HOLD_MATRIX`; gate 1 as global write gate; `incident_hold_cascade` (depth 4) |
| 12 | Program reporting periods | `PeriodReport` with `draft_live_recompute` vs `finalized_snapshot_plus_amendments`; gate 2; `ProgressNote` DRAFT→AMENDED branch; invariant `report_period_partition` (frozen + amendment_net == live) |

Seams not separately entity-ised: nothing was dropped — all twelve are represented.

## Step 3: Copy INSTRUCTION.md — 2026-08-08T18:12:00.000Z

`cp ./INSTRUCTION.md tasks/task_0936_equine_therapy_therapeutic_riding/workspace/INSTRUCTION.md`. Orchestrator independently re-verified all three YAMLs `yaml.safe_load` OK, SCAFFOLD.yaml carries neither design key, and `endpoints:` length == 75.

## Step 4: Generate PRD — 2026-08-08T18:27:00.000Z

The PRD is complete and all audits pass.

## Output

`workspace/PRD.md` — **501 lines, 16,264 words**.

Structure: §1 Introduction (3 paras) · §2 with 12 domain-derived subsections (2.2 emitted verbatim, byte-identical to `section-2.2-response-structure.md`) · §3 with 9 workflow subsections · §4 endpoint table (4 columns) · §5 error table (2 columns).

## Self-audit (all programmatic)

| Check | Result |
|---|---|
| Endpoint coverage | 75 scaffold / 75 in PRD — **0 missing, 0 extra** (table rows compared method+path against scaffold) |
| Error-code coverage | 40 / 40 in §5 table — **0 missing, 0 extra**; all 40 also mentioned in §1–§4 prose |
| Ladder rungs | **44 rendered, contiguous 1…44** as one totally-ordered numbered list in §2.7 |
| Gate precedence | 5 gates rendered in §2.8 as an explicit ordering statement, each pinned to its rung (14→18) with the "gates pre-empt rung 19" consequence spelled out |
| Contract 1 — field names | entities+outputs 164/164, endpoint inputs 96/96 — **0 missing** |
| Contract 2 — rule coverage | 3 OCC rules (endpoint + occ_field + error + 412), 17 status axes with precedence chains, 29 calculations, 5 conservation invariants, both cascades hop-by-hop, all transitions incl. both branches — walked, 0 gaps |
| Contract 3 — §3 path purity | 1002 backtick tokens scanned; 0 slash-leading, 0 bare methods, 0 method+path |
| Enum closed list | §2.9 renders `ENUM_ERROR_FIELD_LIST` exactly (17 fields, order-identical) with "no other field routes here" plus the body-vs-query split |
| Cross-references | 0 dangling §x.y refs; no truncated section |

Timestamp rendering is pinned in §2.5 across four classes (server-minted `.mmmZ`, caller-supplied byte-for-byte, server-derived `.mmmZ`, date-only `YYYY-MM-DD`), including the two fields that switch class mid-life (`hold_release_at`, `certification_expires_at`).

## Un-adjudicated friction points (6)

1. **§3.4** — Re-training is declared out of `INACTIVE`, but qualifications expire on their own anchor and can lapse while the volunteer is still `ACTIVE`. Refused with `ERR_INVALID_STATE`, or accepted as a refresh? Both rendered neutrally.
2. **§3.5** — No ladder rung covers the `IN_TRAINING` ⇒ `supervisor_instructor_id` pairing *at instructor registration* (rung 25 is scoped to session creation). `ERR_VALIDATION` 400 vs `ERR_SUPERVISOR_REQUIRED` 422 left open.
3. **§3.6** — `blocking_gate` on the eligibility read has no declared vocabulary; error-id vs gate-name both rendered. (Fixed: populated iff `admissible` is false.)
4. **§3.7** — Drafting a progress note against a not-yet-`COMPLETED` session: rejected at draft time, or permitted and only blocked at finalize?
5. **§3.8** — A *passing* `preferred_grant_id` has no declared effect. Validated-then-discarded vs promoted to head of the grant candidate order. (Only the rejection is pinned.)
6. **§3.9** — A `SEV_1` instructor suspension when the session names both an instructor of record and a supervising instructor: subject unnamed by the hold matrix.

## Scaffold contradiction found and how it was carried forward

`calculations[grant_candidate_selection].note` claims `ERR_GRANT_RESTRICTION_VIOLATION` is raised **only by `POST /grants`** (both restrictions set with `period_start > period_end`, or `awarded_amount_cents <= 0`). That contradicts ladder rung 41 and the §1.6 error catalog, which both scope it to `preferred_grant_id` on session completion. The note defers to the catalog in its own text ("see the error catalog for the exact condition"), and its alternative conditions are already covered by rung 7 (`period_end >= period_start`, `awarded_amount_cents > 0` → `ERR_VALIDATION`). I carried the rung-41/catalog reading into the PRD and dropped the note's reading entirely — no residual ambiguity is exposed to the implementer.

## Step 5: Generate unit tests — 2026-08-08T19:05:00.000Z

(Steps 5 and 6 were launched concurrently in a single assistant message, giving Step 6 physical isolation from `test_suite/`.)

Test infrastructure and suite complete. `workspace/implementation/` was never read, listed, or grepped.

## Output

`test_helpers/` (9 files, ~1,960 lines): `types.py` (ConditionPolicy TypedDict correctly omits `updated_at`/`version`), `api_client.py` (74 endpoint methods), `api_errors.py` (40 error IDs + status map registered), `assertions.py`, `factories.py`, `constants.py`, `test_users.py`, `fixtures.py` (658 lines, 5 tiers), `__init__.py`.

`test_suite/`: `conftest.py` + 11 domain-named test files, ~4,760 lines.

## Self-audit (F)

| Check | Result |
|---|---|
| `def test_` functions | **105** |
| `Design:` docstring tags | **105** — each unique, none untagged, none dual-tagged |
| Queue A (Difficulty) | 36 tests over **18/18** instances, every one ≥2 tests |
| Queue B (Corner) | 69 tests over **69/69** non-stub instances, every one ≥1 test |
| Tags resolving to a real `name:` in source yaml | 105/105; 0 pointing at `excluded_because` stubs |
| 9 stub cross-references resolve to real difficulty instances | verified, no test emitted |
| Instances SKIPPED | **none** — all 87 source instances translated |
| `skip` / `xfail` / `skipif` | **0 matches** across `test_helpers/` + `test_suite/` |
| PRD citations | every quoted block ≥40 chars in every docstring survives a whitespace-normalized literal match against PRD.md — **0 failures** |
| Response-field names | 111 distinct keys, **all** appear verbatim in PRD.md |
| Datetime string equality (`["<instant field>"] ==`) | **0 matches** — every datetime assertion goes through `assert_same_instant` |
| `compileall` + pyflakes + `pytest --collect-only` | clean; 105 collected |
| Scaffold-leakage grep (`scaffold`, `Table N`, `§1.x/§2.x` outside `Design:`) | none |

`assert_same_instant(a, b)` parses both sides (accepting `Z`, `.mmmZ`, `.ffffffZ`, `+HH:MM`, and date-only promoted to midnight UTC) and compares resolved instants. A separate `assert_millisecond_instant_format` is used only where the PRD's §2.5 three-fractional-digit *rendering* rule is itself the claim under test.

## The six friction points (D)

Five were avoided by construction — the ambiguous branch is never entered:

- **§3.4 re-training out of a non-INACTIVE volunteer** — both retraining calls target a volunteer that is INACTIVE at the logical clock (`retraining_due_at` 2026-04-01 vs clock 2026-05-01; 2027-04-01 vs clock 2027-04-02). `INACTIVE` is the declared from-state, so both readings accept.
- **§3.5 IN_TRAINING registration pairing** — every `IN_TRAINING` registration supplies `supervisor_instructor_id`, so neither `ERR_VALIDATION` nor `ERR_SUPERVISOR_REQUIRED` is ever provoked at registration. The `ERR_SUPERVISOR_REQUIRED` test exercises rung 25 on *session creation*, whose scope the PRD pins explicitly.
- **§3.7 drafting against a not-yet-COMPLETED session** — every progress note is drafted after its parent session reaches `COMPLETED`.
- **§3.8 a passing `preferred_grant_id`** — the only `preferred_grant_id` sent anywhere is one that *fails* its demographic restriction (the rejection the PRD does pin); the successful completion in the same test omits the field entirely, so no test observes what a passing value does to candidate order.
- **§3.9 SEV_1 instructor suspension subject** — every SEV_1 incident is filed against a session with no `supervising_instructor_id`, so "instructor of record alone" and "both instructors on the session" denote the identical single instructor.

One used agreement by construction (option ii):

- **§3.6 `blocking_gate` vocabulary** — in `test_eligibility_reports_release_active_at_booking_and_expired_at_ride` and `test_patching_condition_codes_re_derives_admissibility` I assert only `blocking_gate is None` when `admissible is True` and `blocking_gate is not None` when `admissible is False`. **Reason both readings coincide:** the PRD leaves the *string vocabulary* open (error identifier such as `ERR_HORSE_ON_HOLD`, vs the gate's own name) but pins the *population rule* verbatim — "`blocking_gate` is populated exactly when `admissible` is false and is null when `admissible` is true". Under reading A the field holds a non-empty error-id string, under reading B a non-empty gate-name string; in both, the field is non-null in exactly the same set of states and null in exactly the same set. The predicate I assert (`is None` / `is not None`) is therefore a function only of the pinned population rule and is invariant across the two vocabularies. No assertion anywhere in the suite reads the value of `blocking_gate`.

## Notable adjudication calls

- **Zero-amount allocation lines.** PRD §3.8 says the private-pay line "is **always** emitted, even when its `amount_cents` is 0", and steps 1–2 emit only on "a positive contribution", but steps 3–4 are silent about whether a 0-cent line is written. A faithful reader could emit a 0-cent `SLIDING_SCALE` line for `BAND_D`. I therefore never assert allocation-line *counts* and never assert "no PAYER/SLIDING_SCALE line exists" where the expected amount is 0 (three such sub-assertions from the design yaml were dropped, including the self-contradictory `total_count == 2` in `charge_reverse_twice_returns_invalid_state`). Money assertions use `allocation_total(allocations, source_type)`, which sums and is neutral either way. Absences I *do* assert (`GRANT`/`SCHOLARSHIP` on a `NO_SHOW_FEE` or `LATE_CANCELLATION_FEE`) are safe because the PRD says those steps are "skipped entirely".
- **Goal `current_rating` after reopen** is asserted unchanged (== 4): §3.7 enumerates exactly what reopening changes (status → `ACTIVE`, `consecutive_target_hits` → 0), and clearing `current_rating` would be an unstated side effect.
- **Medical clearance before the incident hold is cleared** is asserted as `ERR_INVALID_STATE`: rung 19 states "Applies to every action endpoint", gate 1's scope excludes this endpoint, and no other catalogue error fits an unmet transition precondition.

## Step 6: Generate implementation — 2026-08-08T19:02:00.000Z

Implementation complete and verified.

## Modules (line counts)

| file | lines | file | lines |
|---|---|---|---|
| `app.py` | 95 | `domain/booking.py` | 102 |
| `start.sh` | 13 | `domain/derive.py` | 260 |
| `requirements.txt` | 1 | `domain/funding.py` | 202 |
| `core/constants.py` | 153 | `domain/gates.py` | 101 |
| `core/ladder.py` | 204 | `domain/policy.py` | 108 |
| `core/store.py` | 117 | `domain/reports.py` | 130 |
| `core/timeutil.py` | 127 | `domain/serialize.py` | 328 |
| `core/errors.py` | 60 | `domain/workload.py` | 160 |
| `core/envelope.py` | 45 | `routes/sessions.py` | 357 |
| `core/lookups.py` | 40 | `routes/goals.py` | 274 |
| `core/numbers.py` | 39 | `routes/incidents.py` | 257 |
| | | `routes/money.py` | 195 |
| | | `routes/releases.py` | 193 |
| | | `routes/volunteers.py` | 182 |
| | | `routes/riders.py` | 175 |
| | | `routes/crew.py` | 147 |
| | | `routes/instructors.py` | 127 |
| | | `routes/horses.py` | 101 |
| | | `routes/period_reports.py` | 71 |
| | | `routes/clockpolicy.py` | 62 |

**Total 4426 lines**, all written in bounded Write/Edit calls.

## B. Endpoint completeness gate
Programmatic diff of the scaffold's `endpoints[]` against a booted `app.url_map` (path params normalised): **scaffold 75 / app 75, MISSING 0, EXTRA 0**. A separate HTTP round additionally *exercised* all 75 (75/75 touched, zero 5xx, zero non-JSON responses).

## C. EADDRINUSE respawn hardening
`app.py` binds its own `SO_REUSEADDR` socket in a 40 × 0.25 s EADDRINUSE-tolerant retry loop and serves via `werkzeug.serving.make_server(host, port, app, threaded=True, fd=sock.fileno()) + serve_forever()` — Werkzeug never gets to convert a bind failure into `SystemExit`. `start.sh` probes `importlib.util.find_spec('flask')` so pip never runs at boot. Tight `kill -9` + immediate relaunch simulation: **15 rounds → 0 start failures**, and a second run after the final edit: **12 rounds → 0 start failures**.

## D1. Timestamp adjudication
All rendering goes through `core/timeutil.py` (`minted`/`derived` → `.mmmZ`; `echoed` → byte-for-byte; date-only → plain strings). HTTP-observed:

- **Class 1 server-minted**: `rider.created_at` `'2026-06-01T09:00:00.000Z'`, `incident.reported_at` `'2026-06-01T09:00:00.000Z'`
- **Class 2 caller-echoed**: `current_utc` `'2026-06-01T09:00:00Z'`, `scheduled_start` `'2026-06-02T14:00:00Z'`, `occurred_at` `'2026-06-02T15:00:00Z'`
- **Class 3 server-derived**: `expires_at` `'2027-05-20T00:00:00.000Z'`, `scheduled_end` `'2026-06-02T15:00:00.000Z'`, `report_due_at` `'2026-06-04T15:00:00.000Z'`
- **Class 4 date-only**: `signed_on` `'2026-05-20'`
- **Mid-life class switches**: `hold_release_at` = `'2026-06-10T00:00:00Z'` (manual hold, echoed) vs `'2026-06-05T15:00:00.000Z'` (incident cascade, derived); `certification_expires_at` = `'2027-01-01T00:00:00Z'` (registration, echoed) vs `'2028-05-31T00:00:00.000Z'` (after renewal, derived).

## D2. Enum-routing adjudication
Implemented as exactly the closed 17-name **body** list: `household_income_band, demographic_group, program_code, funding_mode, activity_type, assessment_type, tier, min_instructor_tier, certification_level, crew_role, hold_type, incident_type, cancellation_reason, domain, restricted_program_code, restricted_demographic, variant`. Routing is by **position**, not name. HTTP-verified members: body `activity_type=NOPE` → **ERR_INVALID_ENUM 400**, body `household_income_band=NOPE` → ERR_INVALID_ENUM, body `cancellation_reason=NO_SHOW` (stored-but-not-input member) → ERR_INVALID_ENUM. Verified exclusions, all **ERR_VALIDATION 400**: query `activity_type`, query `variant` (in the list but never in a body — so this name is reachable only as ERR_VALIDATION), query `status`, `schedule_status`, `charge_type`, `source_type`, `severity`, and non-enum body faults (`weight_lb=-5`).

## E. Six friction adjudications (comment at each code site)
1. **§3.4 re-training out of a non-INACTIVE volunteer** — *accepted as an ordinary refresh*; refusing would make "re-training re-signs every EXPIRED qualification" unreachable, since qualifications expire on their own clock while the volunteer is ACTIVE. (`routes/volunteers.py:134`)
2. **§3.5 trainee registered without a supervisor** — **ERR_VALIDATION 400** (conditionally required field at rung 6/7), not ERR_SUPERVISOR_REQUIRED; rung 25's declared scope is session creation only, so widening it would invent a rung. Unresolvable supervisor id still 404. (`routes/instructors.py:36`)
3. **§3.6 `blocking_gate` vocabulary** — carries the **error identifier** of the first refusing check (e.g. `"ERR_HORSE_ON_HOLD"`); the gate-name reading has no declared vocabulary for the non-gate rungs this read also covers. (`routes/sessions.py:190`)
4. **§3.7 drafting against a not-yet-COMPLETED session** — **permitted**; refusing at draft time would make the finalize-time COMPLETED precondition unreachable. (`routes/goals.py:171`)
5. **§3.8 passing `preferred_grant_id`** — **validated then discarded**; the declared step-1 ranking stays true in every branch. (`routes/sessions.py:272`)
6. **§3.9 SEV_1 instructor suspension with supervision in play** — attaches to **both** instructors; gates 1 and 4 each evaluate the supervisor's SUSPENDED status and the cascade is its only producer. (`routes/incidents.py:154`)

## Ladder / gate ordering as implemented
Strictly ascending 1→44 per request: auth (1–3) in a decorator; ownership (4) evaluated before existence and skipped vacuously when the target is absent; pagination (5); body presence/type-range/enum as three separate passes (6, 7, 8) *before* path/body id resolution (9–13, left-to-right, declared FK field order); then the five gates in fixed order **14 incident-hold → 15 finalized-period → 16 horse-hold → 17 instructor-cert → 18 release**, all above the state rung 19; then 20–32 for booking, 33–39 for crewing, 40 confirm, 41–42 completion, 43 renewal, and **44 OCC last**. Verified with HTTP: gate 3 beats rung 19 on a re-confirm, gate 4 beats gate 5, rung 7 beats rung 9.

## G. Determinism
Ids are valid UUID strings whose first 12 hex digits carry a monotonic creation counter, so ascending `id` == creation order; list ordering is `created_at` ascending with that counter as tie-break under the coarse logical clock. **This is id formatting only — not seeded data.**

## F. Prohibitions
`grep -rniE "sqlite|sqlalchemy|pickle|shelve|json\.dump|open\(|\.write\(|makedirs|/tmp|redis|psycopg|pymongo|csv|seed"` over the tree returns **only three doc-comment lines** stating that nothing is seeded. Storage is plain Python dicts that start empty on every boot; `test_suite/`, `test_helpers/`, `SCAFFOLD_*_DESIGN.yaml` and sibling tasks were never read.

## Step 7: Run tests and iterate — 2026-08-08T19:25:00.000Z

Everything verifies. The work is complete.

## Report

**Result: 105/105 passing in all 8 rounds, across 2 consecutive sweeps.** One real defect found and fixed; it was deterministic (failed in all 8 rounds of sweep 1), so no flakiness was involved.

### Iterations run
2 sweeps (8 rounds each, 2 waves of 4). Sweep 1: 104/105 in every round, same test. Sweep 2: clean.

### Tests deleted
**None.** No test hit PRD silence or a non-derivability collapse.

### Fixes applied to `test_suite/`
- `test_02_releases_and_condition_admissibility.py` · `test_booking_blocked_when_release_expired_but_reassessment_current` — expected `next_due_at` was `2028-03-01`, corrected to `2028-02-29`. PRD §3.1 stamps `next_due_at` at **exactly 365 days** after `performed_on`; the literal had been derived as "same calendar date one year on", which is off by a day because the span from `2027-03-01` contains 29 Feb 2028. The implementation was right. Fix makes the assertion more faithful (exact day arithmetic, not a calendar-year approximation); no assertion was weakened.

### Fixes applied to `test_helpers/` and `implementation/`
**None.** No fixture bug and no implementation bug were found.

### Verification block
1. All 8 results parseable, 105 rows each, `passed=105 failed=0 errors=0`, status set exactly `{'passed'}`. ✅
2. Sorted test-name lists byte-identical across all 8 rounds (n=105). ✅
3. 105 `def test_` = 105 collected = 105 `Design:` tags. ⚠️ **87 unique tags, not 105** — the 18 `Difficulty/*` design items are each realized as a *pair* of tests (ceiling-admitted / one-over-refused, forward-cascade / compensating-cascade, etc.). No two tests are duplicates; this is intentional paired coverage, but it is a genuine deviation from strict tag uniqueness and I'm flagging it rather than papering over it.
4. No `skip`/`xfail`/`skipif` decorators — the 3 grep hits are the words "skipped"/"silently skipped" inside PRD quotations in docstrings. ✅
5. Forbidden-pattern grep over `implementation/`: **zero hits**. Verified genuine, not a grep artifact — storage is `db = {name: {} for name in TABLES}`, empty at boot; time comes solely from a logical `_Clock` seeded at `2026-05-01T00:00:00Z`; `datetime` appears only in `core/timeutil.py` (parse/format) and `domain/workload.py` (`timedelta`). The one `import time` (app.py) is `time.sleep` in the socket-bind retry loop — infrastructure, not a business clock. ✅
6. Route diff vs SCAFFOLD `endpoints[]`: **75 scaffold / 75 live / 75 matched, 0 missing, 0 extra.** ✅
7. Every `round.N.log`: `Killed` exactly once, **0** application tracebacks. ✅
8. `find -newer results.1.json` empty at exit. ✅

### Friction cross-check — all six independently re-derived

| # | §  | Verdict |
|---|-----|---------|
| 1 | 3.4 re-training out of non-INACTIVE | **CLEAN** |
| 2 | 3.5 trainee without supervisor | **CLEAN** |
| 3 | 3.6 `blocking_gate` vocabulary | **AGREEMENT-BY-CONSTRUCTION** |
| 4 | 3.7 note drafted pre-COMPLETED | **CLEAN** |
| 5 | 3.8 passing `preferred_grant_id` | **CLEAN** |
| 6 | 3.9 SEV_1 with two instructors | **CLEAN** |

No DEPENDS. Test-gen's claims held, but two needed correcting in detail:

- **F1** — test-gen called it CLEAN; the *reason* required checking. Both `record_retraining` sites act on a demonstrably INACTIVE volunteer. Site B asserts `status == "INACTIVE"` explicitly first. Site A relies on arithmetic: `last_retraining_on="2025-04-01"` → `retraining_due_at` = +365d = 2026-04-01; clock 2026-05-01 has passed it and `suspended_until` is null, so the §2.11 chain yields INACTIVE. The declared `INACTIVE → ACTIVE` transition, not the ambiguous branch.
- **F3** — verified independently. Only 4 reads exist (test_06:373/375, test_02:425/444), all `is None` / `is not None`, never the value. PRD pins precisely that property ("populated exactly when `admissible` is false"); both candidate vocabularies produce a non-null string when refusing. Confirmed.
- **F5** — test-gen called it CLEAN; I confirmed *why*. The sole `preferred_grant_id` test names a `restricted_demographic="VETERAN"` grant against the default rider's `demographic_group="ADULT"`, so it exercises only the **rejection**, which PRD explicitly pins. The passing branch is never entered.
- **F6** — `session_payload` never emits `supervising_instructor_id`, and no incident test overrides it, so `session_instructors()` returns exactly one instructor; both readings coincide.

**Money chains hand-derived** (three, all exact): the grant+scholarship waterfall (6750 → 3000/3375/150/225, BAND_B 40% of *remainder* vs cap_pct 50% of *gross*); the late-cancellation fee (9000 quoted → 4500 half-fee → 1800/2700, grant step skipped); the no-show fee (9000 → 5400/3600 vs the delivered session's 6750/1350/900, demonstrating PRD's "pays more out of pocket"). All conserve to gross. Also verified: `987.5/5 = 197.5`, `190+30 = 220.0 = max_load` (equality passes), `2.49 ≠ 2.5` (the §2.6 round-then-sum example), age 15 from DOB 2011-01-01.

**Other audits:** all 142 subscripted field names trace verbatim to PRD — the 23 apparent misses are local test-side dict keys (`scenario[...]`, `TEST_USERS[...]`), not response fields. All datetime assertions use `assert_same_instant`; zero raw string equality on derived datetimes. Both list-index assertions are safe (one list has `total_count == 1`; the other is a single-element `stale_goal_ids`).

### Near-miss register (fair only by one incidental value)
1. **`test_eligibility_reports_release_active_at_booking_and_expired_at_ride`** (test_06:375) — fair only because it asserts `blocking_gate is not None`. Adding `== "ERR_RELEASE_EXPIRED"` makes it DEPENDS on F3.
2. **`test_patching_condition_codes_re_derives_admissibility`** (test_02:444) — same shape; `== "ERR_CONDITION_CONTRAINDICATED"` would make it DEPENDS on F3.
3. **`test_retraining_the_volunteer_unblocks_the_same_crew_assignment`** — hinges on `last_retraining_on="2025-04-01"`. Changing it to the factory default `"2026-04-01"` leaves the volunteer ACTIVE at the clock, dropping the call straight into F1's ambiguous branch.
4. **`_sev_1_cascade_scenario`** — one added `supervising_instructor_id=` kwarg on its `book_session` call puts two instructors on the session and makes every suspension assertion DEPENDS on F6.
5. **The four progress-note drafts** — each is preceded by exactly one `complete_session(...)` line. Deleting that line (or reordering) enters F4's ambiguous branch.
6. **test_05's trainee registrations** — dropping the single `supervisor_instructor_id` key enters F2's ambiguous branch (`ERR_VALIDATION` vs `ERR_SUPERVISOR_REQUIRED`).
7. **`test_preferred_grant_failing_its_restriction_is_refused`** — a *weak* near-miss worth stating precisely: making the grant unrestricted enters F5's passing branch but still agrees by construction, because a single candidate is picked identically under both promote and discard. Becoming genuinely unfair needs **two** changes (a second eligible grant ranked ahead of it, plus a passing preference), so this one is further from the edge than the others.

**Orchestrator independent re-verification:** all 8 `results.N.json` re-parsed → 105 rows each, `passed=105 failed=0`, status set exactly `{'passed'}`, sorted name-lists byte-identical across all 8 rounds.

## Step 8: Finalize PRD — 2026-08-08T19:32:00.000Z

Step 8 was NOT skipped: the skip condition needs all four counts at zero and Step 7 made one `test_suite/` fix.

Done. `PRD_FINALIZED.md` written.

## Line counts
- `PRD.md`: 501 lines · `PRD_FINALIZED.md`: 501 lines — **0% line delta**; 2 lines revised (0.40% of lines), 0 lines added or removed, no new sections.

## Changes

- **§2.5 (Time, the Logical Clock, and Timestamp Rendering), "derives by arithmetic" paragraph** — *insert* — appended one sentence pinning that every offset the PRD expresses as *N* days / hours / minutes after (or before) an anchor is exact elapsed-duration arithmetic on the instant (*N* × 24 h for days), never an advance to the same calendar date some number of calendar months/years later, "even where the sentence glosses the offset in years" — `implementation/core/timeutil.py:97-105` (`plus_days`/`plus_hours`/`plus_minutes` are the only arithmetic in the system, all `timedelta`).
- **§3.5 (Instructors and Certification), renewal paragraph** — *revise* — `certification_expires_at is recomputed as 730 days — two years — after renewed_on` → `recomputed as exactly 730 days after renewed_on (promoted to midnight UTC first) — 730 days of elapsed-duration arithmetic per §2.5, which is a nominal two years but is *not* an advance to the same calendar date two years on whenever the span crosses a 29 February` — `implementation/routes/instructors.py:123-124`.

## Per-edit pre-edit search log

**Edit 1 — §2.5 global elapsed-duration clause**
- (a) Subject: every instant derived by adding/subtracting a stated count of days, hours or minutes to an anchor — i.e. the whole family the Step 7 test slip belongs to.
- (b) Paths enumerated (grepped `RELEASE_VALIDITY_DAYS|REASSESSMENT_INTERVAL_DAYS|REASSESSMENT_DUE_WARNING_DAYS|QUALIFICATION_VALIDITY_DAYS|VOLUNTEER_RETRAINING_INTERVAL_DAYS|CERT_VALIDITY_DAYS|CERT_GRACE_DAYS|GOAL_STALE_AFTER_DAYS|HORSE_POST_INCIDENT_REST_DAYS|VOLUNTEER_SUSPENSION_DAYS_SEV_1|INCIDENT_REPORT_DEADLINE_HOURS|LATE_CANCELLATION_WINDOW_HOURS` plus `timedelta|days=|relativedelta` across `implementation/`, and read each): `core/timeutil.py:97/101/105/119` (`plus_days`, `plus_hours`, `plus_minutes`, `week_start`); `routes/releases.py:59` (release `expires_at`, +365) and `:140` (assessment `next_due_at`, +365 — the Step 7 site); `routes/volunteers.py:47,145` (`retraining_due_at`, +365) and `:124,150` (qualification `expires_at`, +365); `routes/instructors.py:124` (cert renewal, +730); `domain/derive.py:76` (assessment `DUE` warning, **−**30 days — the only *before* offset) and `:151` (cert `GRACE`, +60); `routes/goals.py:31` + `domain/serialize.py:220` (`stale_after`, +90); `routes/incidents.py:54` (`report_due_at`, +24/48/72 h), `:133` (rest hold, +3 d), `:144` (SEV_1 suspension, +30 d); `routes/sessions.py:311` (24 h cancellation notice) and the `scheduled_end` = start + `duration_minutes` minute arithmetic; `domain/workload.py:33,38,105` (day window `+1 d`, week window `+7 d`, rest interval 15 min). Every one is a plain `timedelta`; no `relativedelta`, no month/year advance anywhere. Also checked the one genuinely calendar-shaped derivation, `derive.age_years` (`domain/derive.py:87-94`), to make sure the new universal does not mis-describe it.
- (c) Adjustment: scoped the sentence to offsets "this specification expresses as a number of days, hours or minutes after (or before) an anchor" rather than "all date arithmetic", so `age_years` and `current_week_start_date` stay outside it; added "or before" explicitly so `derive.py:76`'s −30-day DUE window is covered; added the "*N* minutes" limb so `scheduled_end` and the 15-minute rest interval are covered. The clause deliberately says nothing about boundary inclusivity — a different subject, pinned elsewhere.

**Edit 2 — §3.5 "730 days — two years —"**
- (a) Subject: `certification_expires_at` when recomputed at renewal.
- (b) Paths enumerated: `routes/instructors.py:110-127` (the only site that *derives* it: `T.plus_days(T.date_to_instant(renewed_on), 730)`, rendered via `T.derived`); the registration path (caller-supplied, `echoed` byte-for-byte); `domain/derive.py:145-153` (`certification_status` reads it for `CURRENT`, `+CERT_GRACE_DAYS` for `GRACE`); `domain/serialize.py` instructor projection; `core/constants.py:29-30`.
- (c) Adjustment: confined the revised clause to the *recomputation* so it cannot be read back onto the registration-time echoed value; left the paragraph's echo-vs-derive sentence verbatim; kept "nominal two years" as a gloss while making the 730-day arithmetic operative.

## Note on the Step 7 item itself
No edit was made at the Step 7 site. PRD §3.1 already pins it verbatim: *"Filing an assessment also stamps the assessment's `next_due_at` at 365 days after `performed_on` (with `performed_on` promoted to midnight UTC first)"*. The failing literal was a test-side derivation slip, not a PRD silence. The two edits exist because the sweep of *sibling* derivations turned up one that was **not** equally explicit — §3.5's `730 days — two years —` gloss, which invites exactly the calendar-advance reading and diverges from impl by a day across a leap year. The remaining siblings all state a bare day/hour count already and were left verbatim.

## Step 9: Complete PRD — 2026-08-08T19:48:00.000Z

Done. Verification passed.

## Result

`workspace/PRD_COMPLETED.md` written as a minimal patch over `PRD_FINALIZED.md`.

- **Line counts:** 501 → 501 (identical); **chars** 116,729 → 140,126 (**+23,397**)
- **52 lines changed**, all expansions — no line got shorter, no line/section added or removed
- **Header diff:** `diff <(grep '^#' PRD_FINALIZED.md) <(grep '^#' PRD_COMPLETED.md)` → **empty**; endpoint/error table rows 119 → 119; file ends correctly at the `ERR_STALE_VERSION` row (not truncated)
- **Counts:** 46 ambiguity-pins, 6 mismatch-revisions
- **All 6 adjudicated friction points pinned** (`grep -c 'Open question for the implementer'`: 6 → **0**)

## Changes

**§2 globals**
- §2.2 — insert — ambiguity — `api_request_timestamp` minted from the logical clock, not wall time — `core/envelope.py:20`
- §2.2 — insert — ambiguity — clock/computed-read/sweep responses are bare objects with no `id`/`version` — `routes/clockpolicy.py:21`
- §2.3 — insert — ambiguity — tie-break on equal `created_at` is monotonic creation order (== ascending `id`); over-range `offset` → empty page, `has_more` false; unresolvable identifier filters → empty page; undeclared query params ignored — `core/store.py:117`, `core/envelope.py:34`
- §2.4 — insert — ambiguity — no-op `PATCH` still bumps; one bump per touched row per request, except one bump per `goal_ratings` **entry** — `core/store.py:96`, `routes/goals.py:263`
- §2.7 r4 — insert — ambiguity — rung skipped when the addressed row is missing; fires ahead of body validation when it exists — `routes/sessions.py:242`
- §2.7 r7 — revise — **mismatch** — the `mounted_minutes ≤ duration_minutes` limb runs after rung 10, so a bad session id reports 404; `period_end ≥ period_start` scope named — `routes/sessions.py:252`
- §2.7 r14 — revise — **mismatch** — gate 1 also requires the placing incident to still be live; subjects are rider/horse/**both** instructors (+volunteer on crew create), in that order — `domain/gates.py:28-44`
- §2.8 — insert — ambiguity — a hold outliving a closed incident falls to gate 3 / rung 36 / rung 20 instead — `domain/gates.py:31`, `routes/incidents.py:233`
- §2.9 — insert — ambiguity — `variant` never occurs in a body, so its closed-list entry is unreachable — `core/constants.py:152`
- §2.10 — insert — ambiguity — null ≡ omitted on input; null always rendered, never dropped — `routes/riders.py:113`
- §2.10 — insert — ambiguity — list projection ≡ read projection; derived-value filters match recomputed values — `domain/serialize.py:12`
- §2.12 — revise — **mismatch** — the frozen-plus-amendment identity is scoped to reversals; late-cancel/no-show fees inside a closed period break it — `routes/sessions.py:296`

**§3.1–3.3**
- §3.1 — insert — ambiguity — rider `date_of_birth` stored/echoed but consulted by nothing — `domain/serialize.py:24`
- §3.1 — insert — ambiguity — `PATCH` null≡omitted, version bumps unconditionally — `routes/riders.py:110`
- §3.1 — insert — ambiguity — `active_release_id` derived per read, filter matches the derived value — `domain/serialize.py:45`
- §3.1 — insert — ambiguity — no bound on `rider_weight_lb`; `assessment_type` consulted by nothing — `routes/releases.py:127`
- §3.1 — insert — ambiguity — superseded assessment's own `version` bumps — `routes/releases.py:161`
- §3.1 — insert — ambiguity — activation: gate 5 first, then two `ERR_INVALID_STATE` preconditions in order — `routes/riders.py:125`
- §3.1 — insert — ambiguity — medical clearance: `note` discarded; four ordered `ERR_INVALID_STATE` faults incl. foreign release — `routes/riders.py:159`
- §3.2 — insert — ambiguity — revoke `reason` discarded; only an `ACTIVE` release may be revoked; superseded release's version bumps — `routes/releases.py:96`
- §3.2 — insert — ambiguity — duplicate `(code, activity)` policies allowed; the most recent governs — `domain/policy.py:22`
- §3.2 — insert — ambiguity — `precaution_tier` as a *read* never errors; reports the running worst tier — `domain/policy.py:50`
- §3.3 — insert — ambiguity — `at_assessment` falls back to declared weight; backriding read live — `domain/policy.py:103`
- §3.3 — insert — ambiguity — workload `on_date` required, validated before the horse resolves; `delivered` filters `day_session_count` too — `routes/horses.py:87`
- §3.3 — insert — ambiguity — manual hold requires `AVAILABLE`, else `ERR_INVALID_STATE` — `routes/horses.py:55`

**§3.4–3.5**
- §3.4 — revise — **mismatch / friction 1** — re-training accepted from any status as a refresh; never `ERR_INVALID_STATE` — `routes/volunteers.py:133`
- §3.4 — insert — ambiguity — sign-off refuses any non-`IN_TRAINING` status; re-training re-signs only `EXPIRED` — `routes/volunteers.py:112,140`
- §3.4 — insert — ambiguity — missing sidewalker `hold_type` is `ERR_HOLD_TYPE_MISMATCH`; unassessed rider → `ERR_CREW_ROLE_NOT_REQUIRED` — `routes/crew.py:43,78`
- §3.4 — insert — ambiguity — release bumps the session only on the `CONFIRMED → CREW_PENDING` reversion — `routes/crew.py:141`
- §3.4 — insert — ambiguity — service-hours params validated before the volunteer resolves, in a stated order — `routes/volunteers.py:161`
- §3.5 — revise — **mismatch / friction 2** — trainee-without-supervisor **and** non-trainee-with-supervisor are both `ERR_VALIDATION`, and the check pre-empts rung 13; stored `supervisor_instructor_id` consulted by nothing — `routes/instructors.py:42-50`
- §3.5 — insert — ambiguity — CE hours may be fractional; `completed_on` discarded; no state precondition — `routes/instructors.py:97`
- §3.5 — insert — ambiguity — renewal refuses `SUSPENDED` as well as `CURRENT`; does not clear `suspended_until` — `routes/instructors.py:112`

**§3.6–3.9**
- §3.6 — insert — ambiguity — six session fields recomputed per read; `supervising_instructor_id` empty-string ≡ absent — `domain/serialize.py:182`
- §3.6 — insert — ambiguity — rung-13 FK order; both daily limbs share one error; the new session never self-conflicts — `routes/sessions.py:55,108`
- §3.6 — revise — **friction 3** — `blocking_gate` carries the error identifier; the exact subset the walk runs (and what it skips); cert always judged at `CURRENT`; `instructor_certification_status` = effective instructor only — `domain/booking.py:82-102`
- §3.6 — insert — ambiguity — confirm runs gates 1/3/4/5 only — `routes/sessions.py:222`
- §3.6 — insert — ambiguity — `mounted_minutes` 0 → 0-cent charge, `FUNDED`; one version bump; clean rollback at rung 42 — `routes/sessions.py:282`
- §3.6 — insert — ambiguity — late-cancel and no-show fees move `billing_status`; neither op passes any gate — `domain/funding.py:142`
- §3.7 — insert — ambiguity — `goals_met_count` derived; goal writes never bump the rider — `domain/serialize.py:43`
- §3.7 — revise — **friction 4** — drafting pre-`COMPLETED` permitted; foreign-rider goal is `ERR_INVALID_STATE`; `author_instructor_id` unresolved — `routes/goals.py:169-188`
- §3.7 — insert — ambiguity — two ordered finalize preconditions; goal state not re-checked; one goal bump per entry — `routes/goals.py:237,249`
- §3.7 — insert — ambiguity — note amendment bumps the report's `version`; `stale_after` derived — `routes/goals.py:272`, `domain/serialize.py:220`
- §3.8 — revise — **mismatch** — supersession hits **every** overlapping `ACTIVE` award, each version-bumped — `routes/money.py:94`
- §3.8 — revise — **friction 5** — a passing `preferred_grant_id` is discarded; ranking untouched — `routes/sessions.py:271`
- §3.8 — insert — ambiguity — hop 4/5 non-firing conditions stated explicitly — `domain/funding.py:180-202`
- §3.8 — insert — ambiguity — overlap check only against `FINALIZED`; 201 already carries live aggregates — `routes/period_reports.py:33`
- §3.8 — insert — ambiguity — amendment deducts that one charge's gross; bumps report version — `domain/funding.py:200`
- §3.9 — revise — **friction 6** — SEV_1 suspends **both** instructors; already-suspended ones skipped — `routes/incidents.py:160`
- §3.9 — insert — ambiguity — the four `*_applied` flags record the matrix, not what landed; each hold has its own from-state — `routes/incidents.py:93,127,161`
- §3.9 — insert — ambiguity — close: volunteer leg reaches only the implicated volunteer; instructor leg only this incident's; booleans always required — `routes/incidents.py:243`
- §4 — insert — ambiguity — trailing slash tolerated; unknown route and unknown method both → `ERR_RESOURCE_NOT_FOUND` 404 — `app.py:23,37,41`

## Highest-yield checklist questions

**(g) cascade legs that do NOT fire** was the biggest single producer — the incident cascade's three from-state guards (rider must be `ACTIVE`, horse `AVAILABLE`, instructor not already suspended) diverge from the `*_applied` flags, and reversal hops 4/5 have two silent non-firing conditions. **(a) fields nothing consults** was next (`assessment_type`, `Instructor.supervisor_instructor_id`, rider `date_of_birth`, and four required-then-discarded body fields: clearance `note`, revoke `reason`, CE `completed_on`, `preferred_grant_id`). **(f) version-bump scope** produced the sharpest single finding — one goal bump per `goal_ratings` *entry*, not per goal. **(b) universal quantifiers** caught the §2.12 conservation identity, which cancel/no-show break because neither passes gate 2. **(i) error routing order** was rich around medical clearance and instructor registration, where scoping faults surface as `ERR_INVALID_STATE`/`ERR_VALIDATION` rather than 404.

---

## Pipeline complete — 2026-08-08T19:50:00.000Z

Final orchestrator verification: PRD.md / PRD_FINALIZED.md / PRD_COMPLETED.md all 501 lines; `^#` header diff FINALIZED→COMPLETED empty (no section added/removed); `find test_suite test_helpers implementation -newer results.1.json` empty (no artifact touched after the passing sweep).



