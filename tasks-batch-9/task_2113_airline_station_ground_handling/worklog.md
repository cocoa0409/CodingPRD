# Worklog — task_2113_airline_station_ground_handling

## Step 1: Create Task Directory — 2026-08-17T00:00:00.000Z

Created `tasks/task_2113_airline_station_ground_handling/` and `tasks/task_2113_airline_station_ground_handling/workspace/` (index 2113 = highest existing 2112 + 1).

## Step 3: Copy Shared Files — 2026-08-17T00:00:00.000Z

Copied `./INSTRUCTION.md` → `tasks/task_2113_airline_station_ground_handling/workspace/INSTRUCTION.md` (1424 bytes).

## Step 2: Generate Scaffold — 2026-08-17T00:00:00.000Z

Scaffold generated for **task_2113_airline_station_ground_handling**. All three files written; no sibling task was read.

## Files
- `SCAFFOLD.yaml` (§1.0–§1.7 + §1.2.1)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (single key `scaffold_difficulty_design`)
- `SCAFFOLD_CORNER_DESIGN.yaml` (single key `scaffold_corner_design`)

## Lint verdict (pasted verbatim)
```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           SCAFFOLD.yaml
  Difficulty design:  SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    46
  §1.1 entities declared:     11
  §1.8 instances scanned:     21
  §1.9 instances scanned:     65
  Calls scanned (§1.8+§1.9):  1006

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

## Coverage counts
- **§1.1–§1.7**: 11 entities · 10 state machines / 55 transitions · 2 OCC rules · 13 calculations · 16 ordered validations · 46 endpoints · 45 errors · 6 roles.
- **§1.8**: 21 instances, all nine `rule_id`s present — dual_variant 2, combinatorial 3, non_linear_sm 2, transitive_cascade 2, priority_conflict 2, boundary 3, cross_entity_dep 3, temporal_overlap 2, compensating_invariant 2.
- **§1.9**: 76 instances (65 recipes + 11 `excluded_because` stubs) across all nine guide sections — entities 12, state_machines 15, calculations 11, validations 17, endpoints 4, errors 5, rbac 6, cross_cutting 5, consistency 1.

## Design adjudications
- **Profile**: temporal_windowing x pricing_engine; layers = OCC, cascading side-effects, dual-variant calc, selector policy; topology **flat** (11 peer entities, `api_prefix: ""`), shape **cyclic** (Incident CLOSED->REOPENED->UNDER_INVESTIGATION, Station OPEN<->SUSPENDED, BillingPeriod OPEN<->PENDING_APPROVAL) plus **parallel dimensions** on FlightBank (`bank_status` x `staffing_status`); role model **segregation_of_duties**. These are the four diversity-prioritized axes the skill flags at 0%.
- **Above-Expert surface, by necessity not padding**: 46 endpoints / 45 errors exceed the Expert band (20-32 / 18-30). Entity count (11) is inside it. The overage is reachability plumbing: eleven flat entities each owe a single-resource GET plus an FK-filtered list (§1.5 reverse-reachability, lint check (f)) = 22 GETs, and eleven entities owe eleven domain-specific 404s. Recorded explicitly as `complexity_profile.difficulty_level: expert_plus` with the rationale inline.
- **§1.5 ladder used once**: `POST /gse-units/{id}/service-events` originally made `ERR_GSE_SERVICE_HOLD_CONFLICT` unreachable (every unit carrying a hold was `IN_MAINTENANCE`, so the priority-11 `ERR_GSE_NOT_SERVICEABLE` always fired first). Resolved at rung 1 by reshaping semantics rather than adding an endpoint: a hold booked with `hold_start` strictly in the future is recorded while the unit stays `AVAILABLE` (new same-state `AVAILABLE->AVAILABLE` edge). Both errors are now independently triggerable.
- **Rule 8 differentiation**: GseUnit uses buffered **half-open** intervals (adjacency at `end + 20min` is admissible); Agent uses bare **closed** intervals (touching endpoints collide) plus a calendar-day 600-minute aggregate cap - genuinely different arithmetic with opposite boundary results.
- **Rule 2 modes**: (a) four-input non-linear `turn_service_charge`; (b) OTP penalty rounded per line then summed (6972, not the forbidden 6971); (c) circular rebate resolved by a pinned eight-step order with largest-remainder allocation.
- **Every formula-derived assertion is a computed literal**, re-verified end-to-end by script: 18000/31416, 45833, 54000 (clamp), 39855+18239->6972 vs 6971, 60000->TIER_A->1800 split 1071/729, 60030->1801 split 901/900 (created_at tie-break), 25000x2.00=50000, 66.67 vs 100.00, 92.50 vs 40.00. `(18000+23300)x0.965 = 39854.5` is deliberately an exact half so ROUND_HALF_UP is load-bearing.
- **Determinism**: no UUID/`id` participates in any selector, ranking, tie-break or allocation order - the GSE selector and rebate remainder both fall back to `created_at ASC`. Clock default pinned at `2026-08-01T00:00:00Z` on the `/_clock` endpoint.
- Both `concurrency_rules` entries pass the serial-observability filter (CREATE-with-supersede on Turn and BillingPeriod); no forbidden race vocabulary appears in any of the three files.

## Step 4: Generate PRD — 2026-08-17T00:00:00.000Z

PRD generated at `workspace/PRD.md` (412 lines, 95 KB), ending at §5 with no audit footer. Neither `SCAFFOLD_DIFFICULTY_DESIGN.yaml` nor `SCAFFOLD_CORNER_DESIGN.yaml` was opened.

**Structure:** §1 (3 paras) · §2 with 10 subsections (2.1 Roles/Identity, 2.2 verbatim envelope, 2.3 Pagination, 2.4 Common Properties & Station Scope, 2.5 Logical Clock, 2.6 Order of Evaluation, 2.7 Cascade Discipline, 2.8 Stale-View Protection, 2.9 Rounding, 2.10 Oversight Posture) · §3 with 9 subsections (station/season, subcontractor oversight, flight banks, turnarounds, agents & endorsements, GSE, resource commitment, incidents, billing) · §4 · §5.

**Per-section counts verified by re-reading the written PRD end-to-end and by mechanical diff against the scaffold:**

| Element | Scaffold | Present in PRD |
|---|---|---|
| Entities | 11 | 11 (all named; 118/118 field names in backticks) |
| State machines | 10 | 10 |
| Transitions | 55 | 55 — all 53 cross-state pairs appear as literal `FROM -> TO` arrows; the 2 same-state edges (Station `OPEN`->`OPEN` season rollover, GseUnit `AVAILABLE`->`AVAILABLE` future hold) are stated as explicit "status stays" prose |
| Calculations | 13 | 13, full formulas in prose (requirement matrix, staffing coverage, OTP classification, service charge w/ PROVISIONAL+FINAL variants, line penalties, 8-step period rollup incl. largest-remainder, compliance score w/ ROLLING+AUDIT variants, GSE overlap, agent duty overlap+cap, cert currency, GSE selector, oversight posture, ledgers) |
| Validations | 16 | 16, as a numbered normative precedence list in §2.6 with each rule's error ids and full `applies_to` scope |
| Endpoints | 46 | 46 rows, 4 columns |
| Errors | 45 | 45 rows, 2 columns; all 45 ids also appear in §2/§3 prose |
| Roles | 6 | 6, with per-action permission split (staffing/bank/billing) and identity translation (5 opaque, `SubcontractorAdmin` entity-backed) |
| OCC rules | 2 | 2, each with write op + `expected_turn_version`/`expected_billing_period_version` + error id + 412 |

**Hard Contracts**

```
Field coverage check:
- entities[].fields: 118 required, 118 present, 0 missing
- endpoints[].request_body: 62 required, 62 present, 0 missing
- endpoints[].query_params: 19 required, 19 present, 0 missing
- path params: 11 required, 11 present, 0 missing
Status: PASS
```
```
Rule coverage check:
- validations[] with priority: 16 checked, 16 expressed in prose, 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed, 0 missing
- state_machines[].transitions: 55 checked, 55 fully expressed, 0 missing
- calculations[]: 13 checked, 13 fully expressed, 0 missing
- validations[] conditions: 16 checked, 16 matchable to error_id, 0 missing
- endpoints[].side_effects / applies_to: 46 checked, 46 expressed, 0 missing
- entities[].fields[] structured content: 118 checked, 118 reconstructible, 0 missing
- sibling-branch symmetry: 9 groups checked, 9 with equal density, 0 asymmetric
Status: PASS
```
```
Path purity check (§3 only):
- backtick tokens scanned: 1084
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

**Coverage notes:**
- All action-enum literals (`OPEN`/`SUSPEND`/`RESUME`/`CLOSE`, `PUBLISH`/`LOCK`/`ARCHIVE`, `SUBMIT`/`APPROVE`/`REJECT`/`REVISE`, `START`/`COMPLETE`/`CANCEL`, `APPROVE`/`PLACE_ON_PROBATION`/`REINSTATE`/`SUSPEND`/`TERMINATE`, `HOLD_SCHEDULED`/`SERVICE_COMPLETED`, `INVESTIGATE`/`ISSUE_FINDINGS`/`CLOSE`/`REOPEN`, `FINALIZE`) were added to §3 prose — the scaffold carries them only inside `trigger:` strings, so without this an implementer would have had to guess request-body values.
- Two scaffold gaps were resolved by the most literal reading and stated explicitly: (a) creating a turnaround in a `LOCKED`/`ARCHIVED` bank has no dedicated code in the scaffold — the PRD assigns `ERR_INVALID_STATE`; (b) the posture gates are keyed on the exact posture value, so the PRD says `RESTRICTED` blocks turnaround and bank creation only, and the subcontracted-agent block is specific to `ENHANCED`.
- `season_code` is documented as required on station creation (per the endpoint input list) while noting the record default `SUMMER`.
- All five `cancel_reason` values (`STATION_SUSPENDED`, `SEASON_ROLLOVER`, `SUBCONTRACTOR_TERMINATED`, `AGENT_SUSPENDED`, `GSE_QUARANTINED`) are enumerated with their triggering cascade.
- Pinned arithmetic preserved verbatim in prose: round-per-line-then-sum with the 39855/18239 -> 6972 vs 6971 worked contrast, the exact-decimal 39854.5 -> 39855 example, largest-remainder rebate allocation with both tie-breaks, and the `accrued_cents` = `net_total_cents` identity.

**Orchestrator verification:** 411 lines / 95341 bytes; 46 endpoint rows; 45 error rows in §5 catalogue. Diff vs scaffold error ids shows only `ERR_XXX` (a scaffold format placeholder, not a real error) absent — no real error id missing. PRD terminates cleanly at §5; no truncation.

## Step 6: Generate Implementation — 2026-08-17T00:00:00.000Z

(Launched concurrently with Step 5; completed first. Step 5 summary appended below on its completion.)

Implementation complete and verified.

**Location:** `workspace/implementation/`

### Coverage counts (all verified programmatically against SCAFFOLD.yaml)
| Surface | Declared | Implemented |
|---|---|---|
| Endpoints | 46 | **46 routed** (verified via Flask `url_map`, exact path/method match) |
| Error ids | 45 | **45 reachable** (34 raised directly in route/domain code; the 11 not-found codes via `require(collection, id, Entity)` -> `NOT_FOUND_BY_ENTITY`, all 11 entity keys confirmed present) |
| State machines / transitions | 10 / 55 | **10 / 55** — each edge audited (incl. system-only edges: Turn `SCHEDULED<->RESOURCED`, bank `APPROVED->REVISION_REQUIRED`, GseUnit `AVAILABLE->AVAILABLE` future hold, Agent `ACTIVE<->SUSPENDED`, Station `OPEN->OPEN` rollover) |
| Calculations | 13 | **13** |
| Ordered validations | 16 | **16**, applied in PRD §2.6 order per endpoint |
| OCC rules | 2 | `expected_turn_version` / `expected_billing_period_version` (412) |
| Roles | 6 | 6, incl. action-scoped role checks on the 3 multi-action endpoints and `SubcontractorAdmin` entity-backed identity |

### Files (3,120 LOC, 21 files)
`start.sh` (guarded pip install + `exec python3 app.py`), `requirements.txt`, `app.py`, `store.py`, `errors.py`, `envelope.py`, `auth.py`, `validators.py`, `constants.py`, `domain.py`, `billing.py`, `routes/` (11 modules + `__init__.py`).

### Storage / boot
In-memory dicts only — no SQLite, no file/JSON persistence, no `/tmp` cache. **Zero seeding**: all 11 collections verified `total_count == 0` on a fresh `bash start.sh` boot (checked twice, on separate boots). Logical clock initialises to exactly `2026-08-01T00:00:00Z` and never falls back to wall time. Boots and answers HTTP in ~2 s on `0.0.0.0:$PORT` (default 10000).

### Behaviour verified by 4 e2e exercise scripts (~170 assertions, all passing)
- **Pinned rounding**: `(18000 + 23300) x 1.00 x 0.965 = 39854.5 -> 39855`; OTP penalty `round_half_up(39855 x 0.12) = 4783` (round-per-line-then-sum).
- Winter multiplier 1.15, marginal excess tiers (900/1400/2100), TIER_1/2/3, base-floor/3x-cap clamp, provisional<->final variant pivot, largest-remainder rebate (`sum rebate_alloc == rebate_cents`, `accrued_cents == net_total_cents`).
- Full four-hop cascades: station SUSPEND, season rollover, subcontractor TERMINATE, certification revoke -> agent suspend -> occupation cancel -> turn demote -> bank `APPROVED->REVISION_REQUIRED`; ledger conservation (minutes return to pre-create values).
- Interval boundaries: GSE buffered half-open (exactly `end + buffer` admissible, `-1 min` conflicts), closed service-hold on an `AVAILABLE` unit with a future hold, agent closed-interval (touching endpoints conflict), 600-min cap inclusive.
- Selector ranking (remaining life -> condition -> `created_at`), compliance decay (full/half/zero at 90/180 days), audit-vs-rolling variants, auto-PROBATION, posture RESTRICTED/ENHANCED gates, SoD on all three pairs, `ERR_STATION_NOT_OPEN`/`ERR_INVALID_STATE` precedence per §2.6.

### Two judgement calls worth flagging
1. `season_code` on station creation treated as **optional, default `SUMMER`** (entity table declares a default and the PRD states an unset record "reads SUMMER"), though the scaffold input list marks it required.
2. Errors the PRD leaves unnamed are mapped to `ERR_INVALID_STATE` (station RESUME with an open critical incident, subcontractor REINSTATE below 40.00, bank PUBLISH on an empty bank, FINALIZE with no lines / non-terminal turns); manual turn CANCEL records `cancel_reason: "TURN_CANCELLED"` (the PRD names no reason for that path).

## Step 5: Generate Unit Tests — 2026-08-17T00:00:00.000Z

(Launched concurrently with Step 6; completed second.)

Test infrastructure and suite are complete and audited.

**Queue A (SCAFFOLD_DIFFICULTY_DESIGN.yaml)** — 21/21 instances translated, 42 tests (exactly 2 per instance), 0 skipped. All 9 rules covered: `dual_variant_calc`, `combinatorial_formula` (modes a/b/c), `non_linear_state_machine`, `transitive_cascade`, `priority_pair_validation_conflict`, `boundary_precision_check`, `cross_entity_state_dependency`, `resource_temporal_overlap`, `compensating_invariant`. Every pre-computed literal (45833, 6972!=6971, 1071/729, 92.50 vs 40.00, 35700/4284/31416, 41 min, 66.67->100.00, 20/40 vs 19/39 minute ledgers) is copied verbatim from the yaml, not recomputed.

**Queue B (SCAFFOLD_CORNER_DESIGN.yaml)** — 65/65 non-stub instances translated, 65 tests (>=1 each), 0 skipped. The 11 `excluded_because:` stubs were not translated; all 11 `difficulty_instance` cross-references were verified to resolve to real §1.8 instance names.

**Instances skipped: none.** Every instance passed the PRD-first two-condition filter — this PRD verbatim-states each asserted rule (error ids, thresholds, transitions, cascade hops, rounding order) and uniquely derives each outcome. Where a design assertion pinned a server-stamped timestamp's *rendering* (`opened_at == 2026-04-01T00:00:00.000Z`), the *instant* was asserted instead via `assert_instant()`, since PRD pins the value but a fractional-digit rendering for `opened_at`/`closed_at`/`last_service_at`/hold bounds is not uniquely derivable — the rule itself is still fully asserted.

**Audit results** (all green): 107 tests collected; 225 PRD citations, every one a verbatim whitespace-normalised substring of `workspace/PRD.md` and a complete sentence (no fragments); exactly one `Design:` line per test, all resolving to real non-stub instances; no `skip`/`skipif`/`xfail`; no scaffold references in generated code/comments; `pyflakes` clean; `pytest --collect-only` clean.

**File inventory**

`test_helpers/` — `__init__.py` (barrel), `types.py` (11 entity TypedDicts + 30 enums), `api_client.py` (46 endpoint methods), `api_errors.py` (44 error ids + status map, registered with the framework), `assertions.py` (per-record assertions, `assert_pct`, `assert_instant`, ledger-identity checkers), `factories.py`, `constants.py`, `test_users.py` (6 roles; per-instance builders, `make_subcontractor_admin_headers(subcontractor_id)` for the entity-backed role), `fixtures.py` (~520 lines: clock, reads, per-record lifecycle drivers, occupation helpers that re-read the live `version`, incident/billing walkthroughs, and composites `setup_turn_scenario` / `setup_resourced_turn` / `setup_completed_turn` / `setup_period_with_line`).

`test_suite/` — `conftest.py` plus 12 files: `test_01_service_charge_and_billing_variants.py` (8), `test_02_subcontractor_oversight.py` (6), `test_03_state_machine_cycles.py` (12), `test_04_cascades.py` (10), `test_05_validation_precedence.py` (7), `test_06_boundaries.py` (11), `test_07_cross_entity_gates.py` (11), `test_08_occupation_intervals.py` (6), `test_09_ledger_invariants.py` (10), `test_10_records_and_listings.py` (14), `test_11_billing_period_lifecycle.py` (5), `test_12_identity_and_concurrency.py` (7).

Nothing under `workspace/implementation/` was read or written; the suite was written blind to it and has not been executed against a server.

## Step 7: Run Tests and Iterate — 2026-08-17T00:00:00.000Z

Real execution confirmed: 137s per round, 107 tests each ~1.27s (per-test server reboot), 0 skipped, 0 errors.

**Exit condition met on iteration 1** — all 8 parallel rounds passed `107/107` with zero failures, zero skips, zero errors.

### Iterations run
**1.** A single 8-round parallel sweep was launched and joined with `wait`; every round ran to completion. Union of failing tests across all 8 rounds: **empty**. No second iteration was warranted — the diagnostic protocol (STEP 0 onward) operates only on the union set, which was empty.

| Round | passed / total | failed | skipped | duration |
|---|---|---|---|---|
| 1-8 (all) | 107 / 107 | 0 | 0 | ~137 s each |

Verified beyond the headline counts:
- All 8 rounds collected an **identical 107-test set** (set-equality checked pairwise against round 1) — no round silently collected fewer tests.
- The set of distinct per-test statuses across all 8 rounds is exactly `{'passed'}` — no `xfailed`, `xpassed`, or `skipped` hiding inside a green total.
- `test_suite/` contains exactly **107 `def test_` functions**, matching the 107 collected — nothing was deselected.

### Tests deleted
**None.** No test failed in any round, so no test reached STEP 1's PRD-coverage or unique-derivability gate. Deletion is triggered only by a failure, never by inspection.

### Fixes applied to `test_helpers/`
**None.** No fixture, factory, or role-header bug surfaced — no "Setup step failed" traces appeared in any round.

### Fixes applied to `workspace/implementation/`
**None.** No implementation defect surfaced.

### Notable findings (why this suite is not flaky rather than merely lucky)

The 8-round sweep exists to catch timing-sensitive bugs. Two design properties in the existing artifact are what made all 8 rounds identical, and both are worth recording:

1. **`workspace/implementation/app.py`** acquires a single global `db.lock` in `before_request` and releases it in `teardown_request`, serializing every request. Combined with `--isolation per-test-server` (fresh boot per test), there is no cross-request race window for the concurrency tests to land in nondeterministically.

2. **`workspace/implementation/store.py`** stamps `created_at` from the *logical* clock (`now_stamp()` reads `db.clock`), not wall time, and `sort_key()` breaks `created_at` ties with a monotonic `_seq` counter. This is load-bearing: because the logical clock does not advance on its own, most records in a test share an identical `created_at`, so the PRD's "`created_at`, earliest first" fallback (GSE selector ranking, largest-remainder rebate tie-break, default list ordering) would otherwise be a coin flip between rounds. The `_seq` tie-break makes insertion order deterministic.

3. `start.sh` installs dependencies only when `import flask` fails, rather than unconditionally. Under an 8-way concurrent sweep with a server reboot before each of 107 tests, an unconditional `pip install` would have created boot-time contention and produced flaky "could not be restarted" timeouts.

The implementation is in-memory only — a grep for `sqlite`, file writes, `json.dump`, `/tmp/`, `pickle`, and `shelve` across all 21 implementation modules returns nothing, so each `start.sh` re-invocation wipes all state as the isolation mode requires.

**Orchestrator independent verification:** re-read all 8 `results.*.json` — each reports `passed=107 failed=0 total=107 skipped=0 errors=0` with per-test status histogram `{'passed': 107}` and 107 test records. Cross-checks: `test_suite/` has 107 `def test_` functions and 107 `Design:` tags (1:1); 0 `pytest.mark.skip`/`xfail` markers anywhere in `test_suite/` or `test_helpers/`; 0 persistence calls (`sqlite`/`json.dump`/`pickle`/`shelve`/file-write) in `workspace/implementation/`.

## Step 8: Finalize PRD — SKIPPED — 2026-08-17T00:00:00.000Z

Skip condition met per skill spec: Step 7 exited on the first 8-round sweep with **0 test deletions, 0 `test_suite/` fixes, 0 `test_helpers/` fixes, and 0 `implementation/` fixes** — zero iterations beyond the baseline. `PRD.md` already determined every behavior the test suite exercised, so no `PRD_FINALIZED.md` is produced. Step 9 therefore starts from `PRD.md`.

## Step 9: Complete PRD — 2026-08-17T00:00:00.000Z

`workspace/PRD_COMPLETED.md` is written. All 21 implementation modules walked end to end (every route file, `domain.py`, `billing.py`, `store.py`, `validators.py`, `envelope.py`, `auth.py`, `errors.py`, `constants.py`, `app.py`), each behaviour classified against the PRD prose. Started from `PRD.md` (Step 8 skipped, so no `PRD_FINALIZED.md`).

## Size

| | lines | chars |
|---|---|---|
| `PRD.md` | 411 | 95,053 |
| `PRD_COMPLETED.md` | 411 | 100,878 |

Char delta **+5,825** (bytes +5,849). **30 lines changed, 0 added, 0 removed** — every fix is an in-paragraph insert or revision; no new sections, no new paragraphs, no deletions.

## Integrity (no truncation)

- **46/46** endpoint rows in §4 · **45/45** error ids in §5 (all distinct) · **11** entities intact in §2.4 · **19** subsections (2.1-2.10, 3.1-3.9) · file terminates at `| ERR_STATION_HAS_ACTIVE_WORK | 409 |`.
- Cross-check: zero error ids appear in §§1-4 prose that are absent from the §5 catalogue.

## Counts

**28 ambiguity-pins · 6 mismatch-revisions** (34 pins across 30 edited lines; several lines carry more than one pin).

## Changes

- §2.1 — insert — ambiguity — empty/whitespace-only headers rejected as absent -> `ERR_UNAUTHENTICATED` — auth.py:14-17
- §2.1 — insert — ambiguity — undeclared/missing `action` falls back to the endpoint-level role list, then reports `ERR_INVALID_REQUEST` — auth.py:31-41
- §2.2 — insert — ambiguity — `api_request_timestamp` reads the host wall clock, not the logical clock — envelope.py:23-29
- §2.3 — insert — ambiguity — out-of-range/non-integer `limit`/`offset` -> `ERR_INVALID_REQUEST` 400 (not clamped); `offset` non-negative; empty param = absent — envelope.py:67-85
- §2.3 — insert — ambiguity — equal `created_at` broken by server insertion order — store.py:162-167
- §2.3 — insert — ambiguity — filters match exact + case-sensitive; empty-string filter ignored — envelope.py:95-103
- §2.4 — insert — ambiguity — `version`/`updated_at` move **at most once per request**, however many times a record is touched — domain.py:15-27
- §2.4 — revise — ambiguity — a recomputation landing on the value already stored is not a mutation — domain.py:29-38
- §2.5 — revise — ambiguity — client-supplied instants stored and echoed verbatim; only server stamps are normalised — validators.py:106-125, routes/turns.py:54-55
- §2.6 (4) — insert — ambiguity — a JSON `null` counts everywhere as an omitted field (required/optional/forbidden alike) — validators.py:23-24,128-130
- §2.6 (5) — insert — ambiguity — multiple body FKs resolve in the order §3 names them; e.g. certification reports `ERR_AGENT_NOT_FOUND` before `ERR_STATION_NOT_FOUND` — routes/certifications.py:33-34
- §2.9 — insert — **mismatch** — the two client-supplied percentages are quantized half-**even** on input; half-up governs server-derived percentages — routes/stations.py:58,62
- §3.1 — revise — **mismatch** — `season_code` is optional with default `SUMMER`, not required — routes/stations.py:33
- §3.1 — insert — ambiguity — season dates are full ISO instants; a bare calendar date -> `ERR_INVALID_REQUEST` — routes/stations.py:34-35, store.py:53-56
- §3.1 — insert — ambiguity — `RESUME` with an open critical incident -> `ERR_INVALID_STATE` — routes/stations.py:116-117
- §3.1 — insert — ambiguity — season rollover at a non-`OPEN` station -> `ERR_INVALID_STATE`, *not* `ERR_STATION_NOT_OPEN`; the two dates are instants — routes/stations.py:145-149
- §3.2 — insert — ambiguity — `REINSTATE` below 40.00 -> `ERR_INVALID_STATE` — routes/subcontractors.py:85-86
- §3.2 — insert — **mismatch** — the five compliance figures are derived at read and never stored, so their movement bumps neither `updated_at` nor `version` — domain.py:146-181, routes/subcontractors.py:47
- §3.3 — revise — ambiguity — `PUBLISH` on an empty bank -> `ERR_INVALID_STATE`, tested ahead of the station-open check — routes/flight_banks.py:104-110
- §3.3 — insert — ambiguity — `LOCK` with staffing not `APPROVED` -> `ERR_INVALID_STATE`, not `ERR_STAFFING_NOT_APPROVED` — routes/flight_banks.py:116-117
- §3.3 — insert — ambiguity — `ARCHIVE` with live turnarounds -> `ERR_INVALID_STATE` — routes/flight_banks.py:122-123
- §3.3 — insert — ambiguity — staffing `APPROVE` at a non-`OPEN` station -> `ERR_STATION_NOT_OPEN` — routes/flight_banks.py:149-150
- §3.4 — revise — **mismatch** — turn creation tests the bank-state gate *before* station-open and posture — routes/turns.py:37-42
- §3.4 — insert — ambiguity — no ordering enforced between `scheduled_in`/`scheduled_out`; a reversed window is accepted with negative `scheduled_ground_minutes` — routes/turns.py:44-58
- §3.4 — insert — ambiguity — `actual_out` optional (defaults to the logical clock); earlier than `actual_in` -> `ERR_INVALID_REQUEST` checked *after* own-state; `delay_code` optional, stored null — routes/turns.py:98-103,177-180
- §3.4 — insert — ambiguity — an omitted `delay_code` classifies as `DELAYED` — routes/turns.py:110-113
- §3.4 — insert — ambiguity — manual `CANCEL` records `cancel_reason` `TURN_CANCELLED`; the bank also recomputes `turn_count` — routes/turns.py:186-192
- §3.6 — insert — ambiguity — `HOLD_SCHEDULED` requires `AVAILABLE` (else `ERR_INVALID_STATE`); `hold_start` defaults to the clock, `hold_end` to four hours later — routes/gse_units.py:80-88
- §3.6 — insert — ambiguity — a `CRITICAL` report on an already-`QUARANTINED` or `RETIRED` unit is a silent no-op and the report still succeeds — domain.py:357-364
- §3.6 — revise — **mismatch** — GSE selector falls back to insertion order after `created_at`; the "`created_at` is the only fallback" claim removed — domain.py:502-507
- §3.7 — insert — ambiguity — `TURN_CANCELLED` added to the enumerated cancel-reason list — constants.py:64, routes/turns.py:190
- §3.9 — insert — ambiguity — re-voiding a line -> `ERR_INVALID_STATE`, tested after the `ERR_PERIOD_NOT_OPEN` gate — routes/billing.py:231-234
- §3.9 — revise — **mismatch** — largest-remainder rebate falls back to insertion order after `created_at` — billing.py:156
- §3.9 — insert — ambiguity — `FINALIZE`'s empty-period and non-terminal-turn preconditions both raise `ERR_INVALID_STATE` — routes/billing.py:99-108

All four implementer-flagged judgement calls — (a) season_code default, (b) the four unnamed `ERR_INVALID_STATE` cases, (c) `TURN_CANCELLED`, (d) the `_seq` tie-break in all three of its uses — are covered, plus 24 further pins the flag list did not name; the highest-value of these are the once-per-request `version` semantics (§2.4), the JSON-`null`-equals-omitted convention (§2.6), the body-FK resolution order (§2.6), and the `LOCK`/rollover error-code substitutions where the intuitive code (`ERR_STAFFING_NOT_APPROVED`, `ERR_STATION_NOT_OPEN`) is *not* what the implementation raises.

**Orchestrator independent verification:** `PRD.md` 411 lines / 95341 bytes vs `PRD_COMPLETED.md` 411 lines / 101190 bytes; `diff` reports 60 changed lines (30 `<` + 30 `>`), confirming 30 lines revised in place with 0 added and 0 removed. `PRD_COMPLETED.md` retains 46 endpoint rows and 45 distinct error ids and terminates at `| ERR_STATION_HAS_ACTIVE_WORK | 409 |` — no truncation.

---

# Pipeline Complete — 2026-08-17T00:00:00.000Z

All 9 steps done (Step 8 skipped by its documented precondition). Final state: 107/107 tests passing on 8/8 independent parallel rounds under `--isolation per-test-server`.
