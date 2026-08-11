# Worklog — task_1114_utility_mutual_aid_crew_mobilization

## Step 1: Create task directory — 2026-08-10T00:00:00.000Z

Pre-assigned output folder `tasks/task_1114_utility_mutual_aid_crew_mobilization` with `workspace/` subdirectory already exists. Step 1 auto-index scan skipped per invocation instruction; directory verified present.

## Step 2: Generate scaffold — 2026-08-10T18:40:00.000Z

All three scaffold artifacts are generated, lint-clean, and pass the manual quality-checklist audits.

## Files written

- `/home/ubuntu/github/CodingPRD/tasks/task_1114_utility_mutual_aid_crew_mobilization/SCAFFOLD.yaml` — §1.0–§1.7 only (no design keys)
- `/home/ubuntu/github/CodingPRD/tasks/task_1114_utility_mutual_aid_crew_mobilization/SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single key `scaffold_difficulty_design`
- `/home/ubuntu/github/CodingPRD/tasks/task_1114_utility_mutual_aid_crew_mobilization/SCAFFOLD_CORNER_DESIGN.yaml` — single key `scaffold_corner_design`

## Design summary (harder-than-expert targeting)

- **Complexity profile**: ledger-reconciliation primary + compliance/audit secondary; layers: dual-variant calculation, cascading side effects, version-pinning on approval, optimistic concurrency. Flat topology, cyclic state shape, segregation-of-duties role model (7 roles, entity-backed ownership scoping via X-User-ID).
- **Surface**: 12 entities, 71 endpoints (incl. `POST /mutual-aid/_clock/set_current_utc` with pinned default `2026-05-01T00:00:00Z`), 31 error codes, 8 calculation rules, 9 state machines (negotiation cycle on AssistanceRequest, independent mobility×readiness dimensions on Crew, dispute cycle on Invoice, rework cycle on TimeSheet), 1 OCC concurrency rule (`schedule-publish-stale-supersede`, 412).
- **Difficulty instances (20, ≥2 per rule)**: dual-variant calcs span three entity domains (Invoice provisional 360964 vs final 201866; per-diem STANDARD 6713 vs ACTUAL 5000; AAR variance 14953); combinatorial formulas cover all three modes (tiered+premium+equipment = 180200; per-day rounding 6713+6713=13426≠13425; fee tier keyed on pre-fee subtotal proven by total 201866 crossing the 200000 boundary at 800bps); depth-3 safety-suspend cascade and depth-2 return cascade; priority pairs (state>fiscal, safety>temporal); boundaries at exactly-480-min OT and at-capacity lodging; cross-entity gates TimeSheet→Crew and Invoice→BillingRateSchedule; half-open lodging vs closed-interval schedule overlap; headcount and money compensating invariants. All numeric asserts are literals verified by executing the formulas in Python.
- **Corner design**: 50 active instances across all nine claim-extraction-guide sections + 9 `excluded_because` stubs pointing at covering §1.8 instances; every §1.6 error has at least one trigger test.

## Verification

- `scaffold_lint.py` verdict, verbatim:

```
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

(Coverage line: 71 endpoints, 12 entities, 20 §1.8 + 50 §1.9 instances, 1017 calls scanned.)

- Additional audits run: forbidden race vocabulary (none), placeholder closure across all 79 named instances (all `${var}` bound by earlier captures; names unique across both files), enum-value closure (removed a dead `UtilityCompany.status` field), file-split key discipline, per-rule instance minimums.

## Step 3: Copy shared files — 2026-08-10T18:42:00.000Z

Copied `./INSTRUCTION.md` to `tasks/task_1114_utility_mutual_aid_crew_mobilization/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-08-10T18:55:00.000Z

PRD generated at `/home/ubuntu/github/CodingPRD/tasks/task_1114_utility_mutual_aid_crew_mobilization/workspace/PRD.md` (319 lines), from the scaffold only — the two withheld design indices were never opened.

**Document structure**
- §1 Introduction (2 paragraphs, EEI mutual-assistance framing; divergence of certified-vs-billed cost views as design driver)
- §2 Global Specifications (10 subsections): 2.1 RBAC with per-role `identity:` prose (ProgramAdmin opaque; 5 utility-backed roles; CrewSupervisor crew-backed); 2.2 verbatim response-envelope block (byte-for-byte verified); 2.3 pagination + list filters; 2.4 logical clock (default `2026-05-01T00:00:00Z`); 2.5 common properties; 2.6 integer-cents / basis-points / round-half-up discipline; 2.7 OCC scoped solely to schedule publication; 2.8 intake posture (threshold exactly 3); 2.9 the 10-family validation precedence with safety-beats-temporal; 2.10 cascades + both compensating invariants
- §3 Business Logic (9 subsections, chronological program lifecycle): enrollment/events, rate schedules + supersession, negotiation + crew commitment, arrival + lodging, safety hold cycle, timekeeping + per-diem pricing, demobilization, invoicing/dispute/settlement, after-action + close
- §4 Endpoint table: 71 rows (matches scaffold), 4 columns only
- §5 Error catalogue: 32 rows, 2 columns only; document ends here, no audit footer

**Hard Contract Reports**

```
Field coverage check:
- entities[].fields: 116 required, 116 present, 0 missing
- endpoints[].request_body/input/output ids: 82 required, 82 present, 0 missing
- endpoints[].query_params: covered (all query filters are entity field names, enumerated in §2.3)
Status: PASS
```

```
Rule coverage check:
- validations[] with priority: 10 families checked, 10 expressed in prose (§2.9 numbered order + per-endpoint orderings in §3.2/3.6/3.8), 0 missing
- concurrency_rules[] OCC rejections: 1 checked, 1 expressed (publish endpoint + expected_superseded_schedule_version + ERR_STALE_SCHEDULE_VERSION/412, stale-view framing), 0 missing
- state_machines[].transitions: 57 checked, 57 fully expressed (from/to states, preconditions with error IDs, side-effect cascades), 0 missing
- calculations[]: 9 checked, 9 fully expressed (crew_daily_billing, per_diem_claim_amount, invoice_totals, mobilization_fee, crew_count_derivation, lodging_occupancy, lodging_overlap_check, intake_posture, aar_cost_variance — all in reconstructible prose, rounding order pinned, no pseudocode), 0 missing
- validations[] conditions: 10 checked, 10 matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: 71 endpoints checked, all expressed, 0 missing
- entities[].fields[] structured content: defaults (15000/20000/480/960 bps/minutes, 0-initializations, null-stamps), enums, and computed-field derivations all reconstructible, 0 missing
- sibling-branch symmetry: 8 groups checked (4 day classifications, STANDARD/ACTUAL, provisional/final, as-certified/as-billed, decline/cancel multi-state siblings, void DRAFT/SUBMITTED, propose vs arbitrate credit bounds, HELD shuttles), 8 with equal density, 0 asymmetric
Status: PASS
```

```
Path purity check (§3 only):
- backtick tokens scanned: 540
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

Additional verifications: §2.2 matches the fixed block byte-for-byte; all 32 error IDs appear in §2/§3 prose; all 7 role names and 66 enum/state values appear in exact backticked spelling; no fuzzy/approximating words and no operator syntax (`==`, `>=`, `min(`, etc.) in §3. All three contracts PASS.

## Step 5: Generate unit tests — 2026-08-10T19:10:00.000Z

Generation complete. Summary of what was produced and verified:

## Deliverables

**`test_helpers/` (9 files, 1632 lines)** at `/home/ubuntu/github/CodingPRD/tasks/task_1114_utility_mutual_aid_crew_mobilization/test_helpers/`:
- `types.py` — 12 entity TypedDicts (all `common_fields: true` here, so all carry id/created_at/updated_at/version) plus 15 status/role enums
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per PRD §4 endpoint (62 methods, including the ProgramAdmin clock driver)
- `api_errors.py` — all 32 error IDs with HTTP status map registered via `set_error_http_status_map`
- `assertions.py` — per-entity assertions plus structural invariants (provisional = subtotal+fee, final = labor+perdiem+fee, AAR variance identity)
- `factories.py`, `constants.py` (canonical S1 rate card + precomputed money figures), `test_users.py` (opaque ProgramAdmin constant + per-instance `make_*_headers` builders for all six entity-backed roles)
- `fixtures.py` — tiered composites: `setup_event_active`, `setup_event_with_accepted_request`, `setup_cleared_arrived_crew`, `setup_demobilized_with_certified_rows`, `setup_submitted_invoice`, `setup_approved_invoice`, plus lodging/AAR helpers; identity threading via `make_*_headers(entity["id"])` throughout

**`test_suite/` (conftest + 14 test files, 2505 lines, 90 tests)** — organized simple→complex: 01 invoice variants, 02 pricing formulas, 03 negotiation/readiness cycles, 04 cascades, 05 validation priority, 06 boundary precision, 07 cross-entity dependencies, 08 temporal overlap, 09 compensating invariants, then corner sections 10–14 (entities/envelope, state machines, calculations, validations/errors, endpoints/RBAC/OCC/consistency).

## Audit results
- **Coverage**: all 20 difficulty instances have exactly ≥2 tests (40 total); all 50 non-stub corner instances have exactly ≥1 test (50 total); the 9 `excluded_because:` stubs were not translated (their difficulty-instance owners carry the assertions).
- **Tag discipline**: AST-verified every one of the 90 test docstrings carries exactly one `Design: Difficulty/<rule>/<name>` or `Design: Corner/<section>/<name>` line as its final line; all 90 tags resolve to real instances in the source YAMLs; no stub tags used.
- **PRD citations**: all 94 quoted citation spans grep verbatim (whitespace-normalized) against `workspace/PRD.md`; citations are rule-bearing (error IDs, thresholds, formulas), not endpoint-titular.
- **No skips**: zero `pytest.mark.skip`/`skipif`/`xfail`; zero scaffold/section references in generated code.
- **Money literals**: every asserted figure (180200, 140600/140930, 105600/96000, 60000, 131000, 6713/13426/5000, 186913/14953/201866, 360964 provisional, 11616/156816 period-filtered) independently recomputed under the PRD's round-half-up discipline — all match.
- `python3 -m py_compile` clean on all files; `pytest --collect-only` collects all 90 tests with no import errors.

No instances were skipped: every non-stub instance in both indices passed the PRD-first two-condition filter (the PRD for this task is unusually thorough — every asserted error ID, threshold, cascade link, and formula step has verbatim §2/§3 coverage).

## Step 6: Generate implementation — 2026-08-10T19:10:00.000Z

`start.sh` boots cleanly with the default PORT 10000, binds 0.0.0.0, exec's the server, and flask is already installed so no pip install happens on repeat boots. The empty store on fresh boot confirms the no-seed constraint.

## Summary

Complete Python + Flask implementation generated at `/home/ubuntu/github/CodingPRD/tasks/task_1114_utility_mutual_aid_crew_mobilization/workspace/implementation/`:

**Files:**
- `start.sh` — executable launcher; guards `pip install` behind `python3 -c "import flask"` so per-test reboots don't reinstall; `exec python3 app.py` for foreground execution
- `requirements.txt` — `flask>=3.0`
- `app.py` — Flask entry point; registers all 44 endpoints, error handlers, listens on `PORT` env (default 10000) bound to `0.0.0.0`
- `db.py` — In-memory store (12 entity dicts, all empty at boot; no seeding) + logical clock (default 2026-05-01T00:00:00Z, settable via `_clock/set_current_utc`)
- `errors.py` — `ApiError` class + all 31 error IDs from the SCAFFOLD catalog
- `response.py` — Envelope helpers producing exactly `meta`/`response_type`/`data` for success, `meta`/`response_type:"error"`/`data.error_id,message` for errors, with `limit`/`offset`/`total_count`/`has_more` pagination fields in meta
- `middleware.py` — `X-User-ID`/`X-User-Role` extraction, role admission, scope checks (ProgramAdmin opaque; HostCoordinator/RespondingCoordinator/HostSafetyOfficer/HostFinance/RespondingFinance entity-backed on UtilityCompany; CrewSupervisor entity-backed on Crew)
- `services/core.py` — Common fields (`id`, `created_at`, `updated_at`, `version`), `touch()` for OCC-style version bump + timestamp refresh on every mutation (incl. cascades), all derived-field recomputes (crew counts, certified/invoiced/paid totals, intake posture, assigned_rooms), 12 serializers
- `services/calcs.py` — `crew_daily_billing` (REST/TRAVEL/STANDBY/WORK with reg/OT/DT banding and round-half-up at each pinned point, storm premium on rounded labor, equipment added last unrounded), `per_diem_claim_amount` (STANDARD with day_factor × meal_factor; ACTUAL with 1.5× cap and round-before-compare), `mobilization_fee` (last tier with min ≤ pre-fee subtotal), invoice sweeps for provisional & final variants

**Verified behaviors in smoke tests:**
- Logical clock set/read works
- Full lifecycle: company → event → activate → schedule draft/publish → request draft/submit/accept → crew commit → arrival → briefing → acknowledge → timesheet draft/submit/certify (computed 72600 cents for 600min WORK @ 6000/hr + 10% premium — matches PRD math)
- `version` increments on every mutation including cascades; `updated_at`/`created_at` use ISO-8601 UTC with 3 fractional digits
- Server starts cleanly via `bash start.sh` from a fresh process

Key fidelity details wired in: validation priority order (auth → role → scope → existence → state → safety → temporal → referential → constraint → fiscal), safety-beats-temporal on certify, OCC on `expected_superseded_schedule_version` returning HTTP 412, closed-interval schedule overlap with supersede-target exemption, half-open lodging stay intervals, depth-3 safety cascade (suspend → timesheets/claims → HELD → request demotion), depth-2 demobilization cascade, compensating invariants (create-then-withdraw leaves `committed_crew_count` unchanged; submit-then-void leaves invoiced totals unchanged), per-claim-day rounding, and segregation of duties across briefing/timesheet/invoice approval paths.

## Step 7: Run tests and iterate — 2026-08-10T19:25:00.000Z

All 8 rounds pass 90/90. Clean sweep achieved.

**Summary**

- **Iterations run:** 2 (initial sweep: 88-89/90 per round; post-fix sweep: 90/90 × 8 rounds, all clean).

- **Tests deleted:** none.

- **Fixes applied to test layer:**
  - `/home/ubuntu/github/CodingPRD/tasks/task_1114_utility_mutual_aid_crew_mobilization/test_suite/test_07_cross_entity_dependencies.py` — `_setup_uncleared_crew_with_submitted_timesheet`: the test `test_certify_succeeds_after_briefing_acknowledged` asserted `certified_amount_cents == 180200`, the canonical amount that includes the 35000c/day bucket truck ("Equipment is added last: the day's amount is the labor figure plus `equipment_daily_total_cents`, unrounded", PRD §3.6). But its setup committed a bare crew with no equipment, so the PRD-faithful implementation correctly returned 145200 (132000 labor + 10% storm premium). STEP 2 test bug: added the canonical `bucket_truck` equipment unit (35000c/day) to the `commit_crew` call, matching the assertion and the fixtures' canonical-scenario docstring. The sibling test sharing the setup asserts only an error_id and is unaffected.

- **Fixes applied to `implementation/`:**
  - `/home/ubuntu/github/CodingPRD/tasks/task_1114_utility_mutual_aid_crew_mobilization/workspace/implementation/start.sh` — replaced the per-boot `python3 -c "import flask"` probe with a `.deps_installed` sentinel (pip install only on first boot). The old check ran a full Flask import on every one of the ~720 per-test server reboots per sweep, doubling boot time; under 8-way parallel load, boot occasionally exceeded the runner's 15s restart window, causing the flaky "server could not be restarted" setup failures in `test_13_validation_corners.py` (`test_mobilization_deadline_passed_rejected` rounds 1/2/8, `test_certification_window_closed_rejected` round 3). No API behavior changed.

- **Verification:** final sweep — rounds 1-8 all 90/90, no flakes.

## Step 8: Finalize PRD — 2026-08-10T19:30:00.000Z

Verification complete. Both Step 7 items resolve to zero PRD changes; `PRD_FINALIZED.md` is a byte-identical copy of `PRD.md`.

## Summary

**Line counts / %-delta:** `PRD.md` = 319 lines, `PRD_FINALIZED.md` = 319 lines, 0% delta. `cmp` confirms byte-identical.

**Changes:** none.

**Per-item analysis (mandatory pre-edit search log — both items resolved to no edit):**

**Item 1 — test_suite/test_07 fixture fix (bucket_truck equipment added to `commit_crew` setup)**
- (a) Subject identified: WORK-day certification amount formula — specifically whether the equipment daily total is added after the premium uplift, unrounded.
- (b) Impl paths enumerated and read:
  - `implementation/services/calcs.py:38-90` (`crew_daily_billing` — all four classification branches: REST→0, TRAVEL→no equipment ever, STANDBY→480min labor + equipment, WORK→banded labor + premium + equipment last at line 90).
  - `implementation/app.py:1192-1194` (certify endpoint prices via `crew_daily_billing` and pins `certified_amount_cents`).
  - `implementation/services/calcs.py:203` (provisional invoice reuses the same `crew_daily_billing` for SUBMITTED sheets — same equipment rule applies).
  - `implementation/app.py:747` (crew creation derives `equipment_daily_total_cents` as sum of daily rates).
  - PRD.md:172 already states verbatim: "Equipment is added last: the day's amount is the labor figure plus `equipment_daily_total_cents`, unrounded."
- (c) Wording adjustment: none needed. The PRD already uniquely determines the behavior the implementation exhibits on every enumerated path (STANDBY and WORK add equipment; TRAVEL and REST do not — all four branches match PRD prose). The Step 7 fix was a pure fixture bug: the test setup omitted the 35000c/day bucket truck its own 180200 assertion required (145200 labor-with-premium + 35000 equipment = 180200). No PRD silence, no mismatch.

**Item 2 — implementation/start.sh `.deps_installed` sentinel**
- (a) Subject identified: dependency-install boot behavior of the launcher script.
- (b) Impl paths enumerated: `start.sh` is the only artifact touched; it execs `app.py` unchanged. No endpoint, state machine, calculation, validation, or error path is affected — the change is `pip install` skipped on re-boot via a sentinel file.
- (c) Wording adjustment: none needed. The PRD specifies API behavior only; deployment/boot mechanics are outside its scope (INSTRUCTION.md, not the PRD, governs the start.sh contract). No PRD edit.

**Result:** `workspace/PRD_FINALIZED.md` is a byte-identical copy of `PRD.md`. A fresh implementer reading it already receives every constraint needed to reproduce the implementation's behavior on the Step 7 sites; Step 7 found no PRD-silence or PRD-mismatch requiring a patch.

## Step 9: Complete PRD — 2026-08-10T19:37:00.000Z

## Summary

**Source file**: `PRD_FINALIZED.md` (319 lines, 57044 chars) → `PRD_COMPLETED.md` (319 lines, 57945 chars, +901 chars).

**Counts**: ambiguity-pins = 3, mismatch-revisions = 5.

**Changes** (each bullet: `{PRD section} — {insert|revise} — {ambiguity|mismatch} — {what changed} — {impl file:line}`):

- §3.2 — revise — mismatch — mobilization-fee tiers: PRD said "the first bracket's threshold must be zero so a bracket always applies"; impl does not validate tier shape and returns fee 0 when no tier threshold is ≤ subtotal — `implementation/services/calcs.py:117-128`, `implementation/app.py:385`.
- §3.2 — revise — mismatch — supersede predecessor status: PRD said "moves that predecessor from `PUBLISHED` to `SUPERSEDED`"; impl moves the predecessor to `SUPERSEDED` regardless of prior status — `implementation/app.py:494-497`.
- §3.3 — revise — mismatch — decline reason: PRD said "an optional `reason` may accompany the decision"; impl does not read or record any payload field on decline — `implementation/app.py:677-691`.
- §3.5 — revise — mismatch — suspend reason: PRD said "an optional `reason` may be recorded"; impl does not read or record any payload field on suspend — `implementation/app.py:911-943`.
- §3.6 — revise — mismatch — timesheet rejection reason: PRD said rejection happens "optionally with a `reason`"; impl does not read or record any payload field on reject — `implementation/app.py:1226-1240`.
- §3.6 — insert — ambiguity — `meals_provided_count` range: PRD said "from zero to three"; impl accepts any integer (no range validation), and a count >3 yields a negative meal factor under STANDARD — `implementation/app.py:1430`, `implementation/services/calcs.py:98`.
- §3.6 — insert — ambiguity — missing rate line for crew_type: PRD was silent; impl treats `hourly_rate_cents` as 0 when no rate line matches, but still adds `equipment_daily_total_cents` for STANDBY and WORK days (REST still bills 0) — `implementation/services/calcs.py:41-49, 51-63, 90`.
- §3.7 — insert — ambiguity — last-crew-out release trigger: PRD said the request is released "when the last of a request's crews reaches a terminal mobility"; impl only runs the release check inside `complete_return`, so a withdrawal that completes the terminal set does not by itself release the request — `implementation/app.py:866-886` (call site at line 881) and `implementation/services/core.py:180-191`.

File path: `/home/ubuntu/github/CodingPRD/tasks/task_1114_utility_mutual_aid_crew_mobilization/workspace/PRD_COMPLETED.md`.

## Pipeline complete — 2026-08-10T19:38:00.000Z

All done conditions met: `workspace/PRD_COMPLETED.md` exists; worklog reaches Step 9; final 8-round stability sweep all pass 90/90 per round (results.1–8.json, 0 failures, 0 flakes).
