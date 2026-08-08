# Worklog — task_0915_correctional_healthcare

Scenario (verbatim): `915. Correctional Healthcare (jail/prison): intake screening & chronic-care enrollment, sick-call & triage, medication (MAR/DOT) administration, off-site & specialty scheduling/transport, co-pay & grievance, continuity & release planning, utilization & audit, mortality/review`

Difficulty parameter: **beyond Expert** (user request: "generate task hard than expert level").

## Step 1: Create task directory — 2026-08-03T00:00:00.000Z

Created `tasks/task_0915_correctional_healthcare/` and `tasks/task_0915_correctional_healthcare/workspace/`. Index 0915 = highest existing (0914) + 1.

## Step 3: Copy shared files — 2026-08-03T00:00:00.000Z

Copied `./INSTRUCTION.md` → `tasks/task_0915_correctional_healthcare/workspace/INSTRUCTION.md` (performed early, alongside Step 1; no dependency on Step 2).

## Step 2: Generate scaffold — 2026-08-03T15:53:00.000Z

All three scaffold artifacts are written to `/home/ubuntu/github/CodingPRD/tasks/task_0915_correctional_healthcare/`.

### Structure delivered

**SCAFFOLD.yaml** (3368 lines)
- **15 entities**: Inmate, IntakeScreening, ChronicCareEnrollment, ChronicCareVisit, SickCallRequest, MedicationOrder, MedicationAdministration, SpecialtyReferral, UtilizationReview, TransportOrder, CopayCharge, LedgerEntry, Grievance, ReleasePlan, MortalityReview. Topology `graph`, role model `segregation_of_duties`.
- **69 endpoints** (above the 48–62 target by 7; the 6 single-resource GETs and the `/specialty-referrals/{id}` read were forced by the lint's FK reverse-reachability rule (f), which needs a `GET /<collection>/{id}` to derive each entity's collection segment before a filtered list counts).
- **10 state machines**, 6 of them non-linear:
  - `Inmate` — **PARALLEL**: `custody_status` and `records_state` are independent axes; freeze/unfreeze moves one without touching the other.
  - `ChronicCareEnrollment` — **CYCLIC** ACTIVE→LAPSED→ACTIVE re-enrollment.
  - `SickCallRequest` — **CYCLIC** TRIAGED→TRIAGED re-triage self-loop.
  - `MedicationOrder` — **BRANCHING with revert** ACTIVE→{HELD, DISCONTINUED, COMPLETED}, HELD→ACTIVE.
  - `MedicationAdministration` — **BRANCHING 4-way terminal fan-out** with a distinct side-effect set per branch.
  - `SpecialtyReferral` — **CYCLIC** SCHEDULED→AUTHORIZED on transport cancel/no-show.
  - `UtilizationReview` — **BRANCHING 3-way fan-out** {APPROVED, DENIED, DEFERRED} + DEFERRED→OPEN cycle + DENIED→PEER_REVIEW→{OVERTURNED, UPHELD}.
  - `Grievance` — **CYCLIC** on two edges (stage escalation DECIDED→FILED, remand REMANDED→UNDER_REVIEW).
- **21 calculations**, 6 dual-variant: `intake_screening_due_at` (NEW_BOOKING restart vs TRANSFER preserve), `sick_call_response_deadline` (upgrade anchors on original submission, downgrade on re-triage instant), `medication_adherence_pct` (DOT event-count vs KOP expected-unit denominator), `copay_amount` (FUNDED vs INDIGENT lien), `ur_turnaround_deadline` (prospective-by-urgency vs retrospective-flat), `bridge_supply_days` (SCHEDULED vs UNEXPECTED tables). Rule-2 modes all three: (a) `transport_lead_time_requirement` nested max/min over 3 inputs, (b) `facility_adherence_index` pinned round-then-average, (c) `copay_amount` pinned pre-charge indigency evaluation.
- **36 validations** organised into a **14-rung explicit priority ladder** (`validation_priority_ladder` block, priorities 1–36). Rung 5 is the mortality/litigation records write-gate, which pre-empts nine rungs below it.
- **2 OCC rules**: `med-order-create-stale-inmate` (parent Inmate) and `transport-order-create-stale-referral` (parent SpecialtyReferral).
- **2 conservation invariants**: INVARIANT-1 money (`sum(LedgerEntry.amount_cents) == Inmate.account_balance_cents`, compensating pair = charge/grievance-reversal), INVARIANT-2 dose counts (five-way outcome partition invariant under the hold/resume pair).
- **Deepest cascade: depth 5**, twice from different triggers — CASCADE-A (death → freeze → discontinue → void → withdraw prescriber escalation) and CASCADE-E (grievance GRANTED → charge REVERSED → REVERSAL ledger entry → balance recompute → indigency flip). Plus depth-3 CASCADE-D (no-show → referral fallback → cap-cancel) and CASCADE-C (diversion → forced DOT → adherence variant switch).
- **32 error codes**, 9 roles.

**SCAFFOLD_DIFFICULTY_DESIGN.yaml** — 24 instances across all 9 rule_ids (2–3 each).
**SCAFFOLD_CORNER_DESIGN.yaml** — 59 instances (48 with full recipes, 11 `excluded_because` stubs).

### Self-check results
- **B — yaml.safe_load**: `OK` for all three files (no bare `?` flow items, no nested-bracket flow items; all optional params quoted as `"limit?"`, all grounds quoted as `"errors[ERR_X]"`).
- **C — constants**: **50 declared**, **0 undeclared**. An automated ALL_CAPS sweep across all three files (excluding enum members, error ids and variant names) returns an empty unresolved set.
- **D — boundary semantics**: every threshold carries an explicit `boundary_semantics:` clause (dose delta −30/60/120 inclusive edges; indigency strictly-less-than 200; lapse grace strictly-after; lead time `>=` accepted at equality; medication spans CLOSED, transport slots HALF-OPEN — deliberately opposite adjacency verdicts).
- **E — arithmetic**: every worked number re-derived in Python from the declared constants (66.67/50.00 DOT-vs-KOP, 77.78 vs pooled 60.00 adherence index, 500/250 copay variants, 480/2880 lead minutes, 11 vs 7 bridge days, all date deadlines).
- **scaffold_lint.py**: `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` (521 calls scanned)
- Extra verification: 83 instance names unique, 0 unresolved `grounds:` refs, all 32 errors referenced by a design instance, all `excluded_because` targets exist, zero forbidden concurrency vocabulary, neither design key present in SCAFFOLD.yaml.

One design note worth flagging: removed a planned `ERR_NO_SHOW_CAP_REACHED` because the cap fires CASCADE-D L3 (referral → CANCELLED), so priority 18 `ERR_REFERRAL_NOT_AUTHORIZED` would always pre-empt it — the code would have been unreachable.

**Orchestrator independent verification:** all 3 files `yaml.safe_load` clean; SCAFFOLD.yaml has neither design key; counts confirmed (15 entities / 69 endpoints / 10 SMs / 21 calcs / 36 validations / 14 ladder rungs / 32 errors / 9 roles / 2 concurrency rules); 22 `constants:` blocks totalling 50 entries, every entry carrying a literal value; independent ALL_CAPS sweep of SCAFFOLD.yaml left only enum members and prose words — 0 undeclared constants.

## Step 4: Generate PRD — 2026-08-03T16:12:00.000Z

`workspace/PRD.md` — **459 lines**, 10 `§2` subsections, 9 `§3` subsections, ends at §5 with no audit footer.

### Coverage report
**Endpoints: 69/69.** §4 table has exactly 69 rows, 4 columns (Method, Path, Description, Authorized Role(s)); set-diff against the scaffold is empty in both directions.
**Error codes: 32/32.** §5 table has 32 rows. Every code also appears at least once in §2/§3 narrative paired with its trigger condition.
**Validations: 36/36, ladder rendered in order.** §2.5 renders all 14 rungs as an ordered numbered list, each naming its error code(s) and HTTP status. Rung 5 (`ERR_RECORDS_FROZEN`, 409) explicitly marked as pre-empting all nine rungs below it, with the two counter-intuitive consequences (freeze beats malformed payload; rung 14 caps/uniqueness/interval are the quietest errors) spelled out. Enum-membership scope (all 19 enum-typed fields) enumerated at rung 8.
**State machines: 10/10, all 51 transitions.** Inmate parallel axes (incl. one-way `DECEASED`→`FROZEN` coupling and permanent-freeze unfreeze refusal), IntakeScreening 3, ChronicCareEnrollment 4 (incl. `ACTIVE`→`ACTIVE` visit self-loop and `LAPSED`→`ACTIVE` cycle), SickCallRequest 6 (incl. `TRIAGED`→`TRIAGED`), MedicationOrder 4, MedicationAdministration 4-way fan-out with divergent per-branch side effects, SpecialtyReferral 7 (incl. `SCHEDULED`→`AUTHORIZED` cycle edge), UtilizationReview 7 (3-way fan-out + `DEFERRED`→`OPEN` + `DENIED`→`PEER_REVIEW`→{`OVERTURNED`,`UPHELD`}), TransportOrder 5, Grievance 7 (both cycle edges). Cascades A–E rendered level-by-level (A depth 5, B depth 4, E depth 5).
**Calculations: 21/21.** The 6 dual-variant forks named with both branches and the fork condition: intake clock (`NEW_BOOKING` restart vs `INTER_FACILITY_TRANSFER` preserved full-assessment anchor), sick-call deadline (**upgrade re-anchors on original `submitted_at`; downgrade on the re-triage instant**), adherence (DOT event-ratio vs KOP time-derived expected-units, clamped), co-pay (`FUNDED` vs `INDIGENT`, with **indigency evaluated on the pre-charge ledger, before the charge posts**, exemption test short-circuiting before any balance read), UR turnaround (prospective-by-urgency vs retrospective-flat 720h), bridge supply (`SCHEDULED` generous vs `UNEXPECTED` truncated table). Pinned rounding order on the facility index (per-order round, then mean round) stated with the forbidden alternative named.
**Constants: 50/50 stated with literal values.** Verified mechanically — zero constant SYMBOL names leak into the PRD as bare symbols.
**Boundary semantics:** all rendered as explicit-edge prose — dose deltas (−30 on-time / −31 missed; 60 on-time / 61 late; 120 late / 121 missed), indigency strictly-less-than 200¢ (200 not indigent, 199 indigent) on both parts, chronic lapse strictly-after grace, transport lead accepted at equality, cancel cutoff cancellable at equality, and the deliberately opposite adjacency verdicts (medication spans **closed** → touching dates collide; transport slots **half-open** → touching slots do not).
**Contract reports:** Field-Name Coverage 116/116 entity fields, 63/63 endpoint input identifiers, 0 missing — PASS. Rule Coverage 2/2 OCC rules (`expected_inmate_version`/`ERR_STALE_INMATE_VERSION` 412; `expected_referral_version`/`ERR_STALE_REFERRAL_VERSION` 412), 51/51 transitions, 21/21 calculations, 36/36 validation conditions, both conservation invariants, sibling-branch symmetry on the UR 3-way, MedAdmin 4-way and co-pay 3-way fan-outs — PASS. §3 Path Purity 1097 backtick tokens scanned, 0 violations — PASS.

### SCAFFOLD RULES FOUND UNDER-SPECIFIED
Two items required a judgement call. Neither number was invented — both are scope/error-routing questions where the scaffold's prose admits more than one reading:
1. **`ERR_RECORDS_FROZEN` scope boundary (validation priority 7).** `applies_to` does not say whether transport-order, ledger-deposit, release-plan, or release/death-event/records-freeze endpoints are inside "referral"/"clinical". Resolved by following the scaffold's own grouping in validation priority 5 (specialty-referrals + utilization-reviews + transport-orders = one "referral record" family): the PRD gates all 28 intake/chronic-care/sick-call/medication/referral/UR/transport/co-pay mutations, and explicitly excludes custody+records events, ledger deposits, release plans, grievances and mortality reviews.
2. **Error code for a non-`DEPOSIT` `entry_type` on the operator ledger endpoint.** `CHARGE`/`LIEN`/`REVERSAL` are legal enum members so rung 8's enum-membership check passes and no rule names the rejection. PRD routes it to `ERR_VALIDATION` (400) as a payload-value failure at rung 8.

**Orchestrator adjudication of the two under-specified items:** both are now pinned concretely in PRD prose (a scope list and an error routing), not left as named-but-valueless constants, so neither is the blocking `[[prd-bench-scaffold-undeclared-constants]]` pattern. No scaffold patch required; proceeding to Steps 5/6.
**Orchestrator independent verification:** PRD.md 458 lines; 0 constant symbols leaked as bare tokens; all 32 error codes present; all 69 scaffold endpoint paths present in the text.

## Step 5: Generate unit tests — 2026-08-03T16:40:00.000Z

### Output
**11 test files, 105 `def test_` functions** in `test_suite/`: `conftest.py`, `test_01_booking_and_intake.py`, `test_02_chronic_care.py`, `test_03_sick_call.py`, `test_04_medication_orders.py`, `test_05_medication_administration.py`, `test_06_utilization_review.py`, `test_07_transport.py`, `test_08_copay_and_ledger.py`, `test_09_grievances.py`, `test_10_release_and_mortality.py`, `test_11_access_control.py`

**`test_helpers/` inventory**: `__init__.py` (barrel), `types.py` (34 enums + 14 entity TypedDicts — `ChronicCareVisit`/`LedgerEntry` carry only `id`+`created_at`), `api_client.py` (69 endpoint methods, one per PRD §4 row), `api_errors.py` (32 error ids + status map), `assertions.py` (`assert_same_instant`/`parse_instant`, per-entity assertions, `assert_money_invariant`, `assert_dose_partition`, `bucket_counts`), `factories.py`, `constants.py`, `test_users.py` (8 opaque roles + per-instance `make_inmate_headers` for the entity-backed `Inmate` role), `fixtures.py` (942 lines, 60+ composite helpers incl. the depth-5 cascade, no-show, hold/resume, dual-adherence and billing-grievance scenarios).

### Coverage
- **Queue A (Difficulty): 24 / 24 instances translated**, every one with ≥2 tests (49 Difficulty-tagged tests).
- **Queue B (Corner): 48 / 48 non-stub instances translated**, each with ≥1 test (56 Corner-tagged tests). The 11 `excluded_because` stubs were verified to cross-reference real difficulty instances and were **not** translated.
- **SKIPPED instances: none.** Every non-stub instance passed the PRD-first two-condition filter.
- One assertion deliberately dropped inside an otherwise-generated test: `observed_swallow == null` after a successful KOP record (`kop_order_rejects_observed_swallow_field`) — PRD states the field must be *absent from the request*, never what the stored/serialized value becomes (default-value silence pattern). The instance's primary assertions (422 `ERR_KOP_OBSERVATION_FORBIDDEN`, then 200 with `outcome == ADMINISTERED`) are asserted.

### Verification performed
- Every test carries **exactly one** `Design:` line; all 105 tags resolve to real, non-stub instances (AST + YAML cross-reference).
- **149 PRD citations checked; 0 non-verbatim** — each survives a whitespace-normalized literal match against `PRD.md`, all ≥8 words.
- **No `pytest.mark.skip` / `skipif` / `xfail` / `pytest.skip()` anywhere.**
- `compileall` clean; `pytest --collect-only` collects 105 tests.
- Every datetime assertion goes through `assert_same_instant`; no raw string equality on a timestamp field anywhere.
- Base URL from `API_BASE_URL`; every fixture sets the logical clock and builds all state from scratch through declared endpoints.

### Ladder / boundary notes flagged
- Rung-5 fixtures isolated: the two `ERR_RECORDS_FROZEN` tests freeze *only* after all other preconditions are satisfied; paired tests unfreeze to expose the rung-11 error underneath.
- Opposite edges encoded literally: medication spans closed (`start 05-10 == end 05-10` collides; `05-11` does not), transport slots half-open (`11:59` collides; `12:00` legal), dose deltas `+60` ON_TIME / `+61` LATE, indigency `200` not indigent / `199` indigent, transport lead accepted at exact equality (`lead_minutes == 480`), release-plan lead accepted at exactly 7 days, peer-review window closed at exactly +48h, grievance filing closed at exactly +15d.
- `records_unfreeze_cannot_reopen_a_decedent_record` asserts `ERR_INVALID_STATE`: PRD states the refusal verbatim but names no error id at that site; rung 9 is the only ladder rung that fits (rung 6 is explicitly limited to six named operations), so it is uniquely derivable — **worth watching if the implementation picks differently.**

**Orchestrator independent verification:** 105 `def test_`; 0 skip/xfail/skipif markers; Design tags 49 Difficulty + 56 Corner = 105 (exactly one per test); 9 helper modules present.

## Step 6: Generate implementation — 2026-08-03T16:40:00.000Z

### Module inventory (3,556 lines total)
`app.py` 50 (Flask app factory, error handlers, `__main__`), `ladder.py` 290 (14-rung validation ladder engine), `calc.py` 305 (all 21 calculations + read-time projections), `serializers.py` 273 (15 entity → JSON projections), `cascades.py` 154 (Cascades A/B/D + shared multi-row helpers), `constants.py` 142, `store.py` 104 (in-memory dicts, logical clock, id/version/timestamps), `timeutil.py` 99 (`Ts` instant+rendering type), `envelope.py` 86, `money.py` 85 (ledger append, co-pay six-step, Cascade E reversal), `errors.py` 50 (32-entry error→status catalogue), `routes/` 12 files 1,918 lines (meds 301, referrals 252, grievances 233, transport 209, chronic 185, sickcall 172, release 145, inmates 130, trust 110, screenings 92, clock 42, reports 30, `__init__` 17). Plus `start.sh` (guarded `pip`, `exec python3 app.py`, `$PORT`, `0.0.0.0`, foreground) and `requirements.txt`.

### Completeness gate (all four numbers)
Scaffold endpoint count **69** / registered route count **69** / **MISSING 0** / **EXTRA 0**. Diffed programmatically with scaffold `{id}` normalized against Flask `<id>`.

### C1 — timestamp rendering rule adopted
Three-way rule in `timeutil.Ts` (every instant carries both its `datetime` and the exact string to emit):
1. **Caller-supplied instants echoed byte-for-byte verbatim** — `booked_at`, `prior_full_assessment_at`, `scheduled_release_date`, `start_date`, `end_date`, `scheduled_at`, `appointment_at`, `grieved_event_at`, `planned_release_at`, `death_at`.
2. **Server-generated stamps in one canonical format** — `YYYY-MM-DDTHH:MM:SS.mmmZ` (PRD §2.4): `created_at`, `updated_at`, `submitted_at`, `triaged_at`, `seen_at`, `enrolled_at`, `recorded_at`, `acted_at`, `opened_at`, `decided_at`, `requested_at`, `authorized_at`, `stage_entered_at`, `completed_at`, `closed_at`, `api_request_timestamp`.
3. **Derived instants (anchor + whole hours/days) also canonical**, per PRD §2.8's explicit sentence that computed deadlines are always `.000` — `due_at`, `next_due_date`, `response_deadline_at`, `deadline_anchor_at`, `turnaround_deadline_at`, `response_due_at`, `due_at_snapshot`. A derived value does *not* inherit its caller-supplied anchor's style; PRD pins that explicitly.

### C2 — enum error routing rule adopted
**Every enum-typed request-body field yields `ERR_INVALID_ENUM` (422) for an off-domain value, uniformly** — whether or not the field is one of the 19 named in PRD §2.5. Single `ctx.enum(field, domain)` check for all, including the two fields §2.5 does *not* name (`disposition`, `findings_code`) and endpoint-scoped domains. A **missing** or **wrongly-typed** value on the same field is `ERR_VALIDATION` (400), running earlier inside rung 8 (sub-order: required → type/range → enum). Enum validation applies to **body fields only**; list-endpoint query filters match nothing rather than 422.

### The 14-rung ladder
One engine in `ladder.py`. `Ctx.at(rung, fn, sub)` *registers* checks; `Ctx.run()` executes them sorted by `(rung, sub, registration_order)`, first failure raising and short-circuiting — lowest rung always wins. No handler uses ad-hoc `if` chains; every handler is a declarative registration list ending in `ctx.run()`. Registrars: `path_inmate`/`body_inmate`/`need`/`need_body_ref` (3+4), `freeze_gate` (5), `custody_gate` (6), `occ` (7), `require`/`check_type`/`check_range`/`enum` (8), `state`/`status_in` (9), `cross_state` (10), `safety` (11), `segregation` (12), `temporal` (13), `caps` (14). Rung-5 primacy verified live: a frozen inmate returns `ERR_RECORDS_FROZEN` for both an empty payload and an off-enum payload, while rung 2 still beats it.

### Boundary edges (all verified live)
Closed medication date spans vs half-open 240-min transport slots; dose deltas −30 ON_TIME / −31 MISSED_WINDOW / +60 ON_TIME / +61 LATE / +120 LATE / +121 MISSED_WINDOW; indigency strictly `< 200`; transport lead accepted at exact equality (480 = 480); screening overdue and enrollment lapse strictly-after; grievance filing/escalation and peer-review windows closed; release-plan lead accepted at exact equality; mortality review closed exactly at `due_at` is on time.

### Live boot smoke test
`cd implementation && PORT=18940 bash start.sh` then `POST /inmates` → **HTTP 201**, `booked_at` echoed verbatim, `created_at` `2026-05-01T00:00:00.000Z`, `version:1`, `indigent_flag:true`; `GET /reports/facility-adherence?facility_code=F1` → **HTTP 200**. Beyond that: **three functional smoke suites, 133 assertions, 0 failures** covering intake clocks, chronic tiers/escalation/lapse/re-enroll, sick-call triage upgrade vs downgrade anchors, co-pay FUNDED/INDIGENT/EXEMPT, OCC on both writes, supersede + overlap, DOT/KOP discipline, Cascade C, UR defer/reopen/peer-review, transport lead + escort + no-show penalty + supersede, Cascade E money invariant, hold/resume dose-count invariant, Cascade B, Cascade A (all seven consequences), mortality review.

### Storage
**In-memory only.** 15 plain Python dicts in `store.py` module globals. No SQLite, file writes, `/tmp`, or pickle. **Store rows at boot: 0**; logical clock at boot `2026-05-01T00:00:00Z`. Nothing seeded.

### PRD adjudications (three internal conflicts)
1. **Closing a seen sick call is NOT freeze-gated.** §2.6's summary list includes "closing", but §3.3 states "the freeze gate is not consulted on this final step, whose only precondition is that the request is `SEEN`". Followed the specific rule.
2. **Only the *resume* direction of `hold-status` is custody-gated.** §2.6 says "holding or resuming"; §3.4 states the resume additionally requires `IN_CUSTODY`. Followed the specific rule.
3. **Re-enrolling a lapsed enrollment IS custody-gated** (`ERR_INMATE_NOT_IN_CUSTODY` at rung 6) per §3.2, even though not in §2.6's six-item list.
Also: closing a mortality review checks `corrective_action_count >= 1` *before* the target-state check within rung 9, else `ERR_MORTALITY_REVIEW_INCOMPLETE` would be unreachable. Attaching a corrective action accepted from both `OPEN` and `CORRECTIVE_ACTIONS_ISSUED`.

**Orchestrator independent verification:** `start.sh` execs `app.py` which exists; layout-agnostic route-decorator grep = 69; live `app.url_map` = 69 (matches scaffold's 69 exactly — no partial-write gap); repo grep for `sqlite|pickle|shelve|json.dump|open(...,'w')|/tmp` returns nothing.

## Step 7: Run tests and iterate — 2026-08-03T16:52:00.000Z

Verification complete. The 8-round sweep is a genuine clean pass on the first iteration.

**Iterations run:** 1 (a single 8-round sweep; no fix cycle was needed).

**Final per-round results:**

| Round | Result | Duration |
|---|---|---|
| 1 | 105/105 passed, 0 failed, 0 errors, 0 skipped | 121.8s |
| 2 | 105/105 | 121.2s |
| 3 | 105/105 | 121.5s |
| 4 | 105/105 | 121.4s |
| 5 | 105/105 | 123.4s |
| 6 | 105/105 | 123.1s |
| 7 | 105/105 | 121.7s |
| 8 | 105/105 | 124.0s |

Union of failing tests across all 8 rounds: **empty**. No flakiness signal — no test passed in one round and failed in another.

- **Tests deleted:** 0
- **Assertions relaxed to `validate_error_is_one_of`:** 0
- **Fixes applied to `test_helpers/`:** 0
- **Fixes applied to `test_suite/`:** 0
- **Fixes applied to `implementation/`:** 0

**Task-specific watch item resolved without adjudication.** The flagged test (design instance `records_unfreeze_cannot_reopen_a_decedent_record`, implemented as `test_10_release_and_mortality.py::TestDeathCascade::test_a_death_induced_freeze_can_never_be_lifted`) passed in all 8 rounds — the implementation independently routes the decedent-unfreeze refusal to `ERR_INVALID_STATE`, matching the test. STEP 1b was therefore never triggered; no relaxation or deletion was warranted.

**Integrity checks performed to rule out a false-clean:**
- Per-test-server isolation confirmed active by reading the runner's `pytest_plugin.py` — `pytest_runtest_setup` calls `_kill_port` + `_restart_server` before *every* test. Child stdout goes to `DEVNULL`, which is why only one Flask banner appears per round log; the single `Killed` at test #1 is the pre-boot server being swapped out, as expected. All 105 tests ran against a freshly booted, empty server.
- `results.N.json` parsed structurally: 105 test entries per round, every `status == "passed"`, `skipped == 0`.
- 0 occurrences of `pytest.mark.skip` / `skipif` / `xfail` / `pytest.skip()` in `test_suite/` or `test_helpers/`.
- 105 `def test_` functions collected, matching the stated test count.
- Live `app.url_map` = **69 routes exactly**.
- Storage in-memory only: 15 plain dicts in `store.py`, **0 rows at boot**, 0 grep hits for `sqlite|pickle|shelve|json.dump|open(...,'w')|/tmp|redis|psycopg`.

**Orchestrator independent re-verification of the zero-fix pass** (a clean first sweep is indistinguishable from a false-clean without this): all 8 `results.N.json` present and parseable; each contains **105 individual test rows** (not just an aggregate counter) with status `passed` for every row; the **test-name sets are identical across all 8 rounds** (no round silently collected a smaller suite); `def test_` count in `test_suite/` (105) == runner's collected count (105).

## Step 8: Finalize PRD — SKIPPED — 2026-08-03T16:53:00.000Z

Skip condition met: Step 7 exited on the first 8-round sweep with 0 deletions, 0 `test_suite/` fixes, 0 `test_helpers/` fixes, and 0 `implementation/` fixes. `PRD.md` already determined every behavior the tests exercised, so there is no `<step_7_diff>` to apply and no `PRD_FINALIZED.md` is produced. Step 9 runs against `PRD.md` directly and is the sole completeness pass.

## Step 9: Complete PRD — 2026-08-03T17:01:00.000Z

`workspace/PRD_COMPLETED.md` written from `workspace/PRD.md` (no `PRD_FINALIZED.md` — Step 8 skipped).

**File sizes** — `PRD.md` 458 lines / 101,792 chars → `PRD_COMPLETED.md` 466 lines / 120,462 chars (**+8 lines, +18,670 chars**). 41 paragraphs revised in place, 4 paragraphs inserted (all inside existing sections; no new sections, no table or heading changes).

**Counts — 34 ambiguity-pins, 8 mismatch-revisions (42 changes).**

### Mismatches (PRD said something the implementation does not do)
- **§2.3** — revise — "**Four** endpoints order differently" → **Three** (only `scheduled_at`, `recorded_at`, `opened_at` differ) — `routes/*.py` sort_rows calls
- **§2.5 rung 8** — revise — the "full set" of enum fields omitted `disposition` and `findings_code`, both routed to `ERR_INVALID_ENUM` — `routes/screenings.py:73-74`
- **§2.6** — revise — freeze list wrongly included **closing** a sick-call request; moved to the not-guarded families (now five, not four) — `routes/sickcall.py:160-167`
- **§2.6** — revise — custody gate is **seven** ops not six: added **re-enrolling a lapsed enrollment**, and "holding or resuming" → **resuming only** — `routes/chronic.py:106`, `routes/meds.py:126-131`
- **§2.6** — insert — release/death-event enforce `IN_CUSTODY` at rung 9 as `ERR_INVALID_STATE`, not via the custody gate — `routes/inmates.py:68,89`
- **§2.9 / §3.6** — insert — Cascade D at the no-show ceiling bumps the referral's `version` **twice** in one request — `cascades.py:143-149`
- **§3.2** — revise — "Severity is not stored" → severity **is** stored and echoed, and is not rewritten by a tier escalation — `serializers.py:56`, `routes/chronic.py:164`
- **§3.9** — insert — mortality-review close tests `corrective_action_count` **before** the target state, so an `OPEN` review with no actions reports `ERR_MORTALITY_REVIEW_INCOMPLETE` — `routes/release.py:135-136`

### Ambiguity-pins (PRD silent) — 34
- **§2.2** — `api_request_id` = `req_` + 20 uppercase-alnum chars; `api_request_timestamp` from the **host wall clock**, not the logical clock — `envelope.py:14-23`
- **§2.3** — non-integer/empty `limit`/`offset`; params evaluated after the ladder; out-of-range offset → empty page, `total_count` full, `has_more` false — `envelope.py:38-46,63-86`
- **§2.3** — tie-break on **server insertion sequence**, never on `id` — `store.py:92-98`
- **§2.3** (new para) — filters are exact case-sensitive raw-string matches, never enum-validated (`?status=BOGUS` → empty page); rung 8's enum check is **body-only**; empty filter = absent; Inmate scoping applied first
- **§2.4** (new para) — every response projects the **whole** row, identical shape across create/transition/read/list; absent values are `null` not omitted; `_seq` and the grievance decision instant never projected — `serializers.py` (all 15)
- **§2.4** (new para) — the **three-way timestamp rule**: caller-supplied echoed byte-for-byte; server-generated canonical `.mmmZ`; derived deadlines canonical and **not** inheriting their anchor's style; `prior_full_assessment_at` changes class on FULL_ASSESSMENT completion — `timeutil.py:1-95`, `routes/screenings.py:86`
- **§2.4** — clock accepts any instant incl. backwards; returns **200 with an empty object** — `routes/clock.py:23,42`
- **§2.5 rung 3** — path/body inmate id compared as supplied (403 even for a nonexistent id); transitive ownership skipped so rung 4 reports 404 — `ladder.py:94-128`
- **§2.5 rung 8** — a body that is not a JSON object is the **first** sub-step, before required-fields — `ladder.py:33-36,182-190`
- **§2.7** (×2) — absent/null/non-integer version field falls to rung 8 → `ERR_VALIDATION`; 412 reserved for a well-formed wrong integer — `ladder.py:169-179`
- **§2.9** (new para) — every negative branch of Cascades A–E spelled out (skipped legs, LAPSED enrollment untouched on release, diversion inert on an already-DOT order, etc.) — `cascades.py:76-154`, `routes/meds.py:294`
- **§2.9** — version accounting is **per row per request**, not per level — `cascades.py:42-56`
- **§3.1** — the three optional booking fields default on explicit `null` too — `routes/inmates.py:44-46`
- **§3.1** — no uniqueness key on `screening_type`; initial null/false fields — `routes/screenings.py:26-35`
- **§3.2** — visit recording: rung-9 `ERR_INVALID_STATE`, not custody-gated, one version bump — `routes/chronic.py:140,170`
- **§3.3** — `POST .../see` returns **200** with the sick-call request despite creating a charge — `routes/sickcall.py:157`
- **§3.4** — `drug_name` must be non-empty; rung-8 type sub-step order (types → range → date comparison) — `routes/meds.py:32-44`
- **§3.4** — MAR row initial `observed_swallow`/`administered_by_user_id` null, `diversion_observed` false; **no parent-order status precondition**; parent order's `version` **not** advanced — `routes/meds.py:181-202`
- **§3.4** — `observed_swallow` presence = **non-null**; `false` satisfies DOT; non-boolean is rung-8; written only when non-null — `routes/meds.py:243-256,273-274`
- **§3.4** — `ADMINISTERED` does **not** clear `escalated_to_prescriber` — `routes/meds.py:278-281`
- **§3.4** — pill-count deltas may be zero/negative; no status or custody precondition; recomputes by the current `route_mode` — `routes/meds.py:163-178`
- **§3.4** — `facility_code` is a **required query param** → `ERR_VALIDATION`; unknown code is an empty facility, not an error — `routes/reports.py:17-25`
- **§3.5** — `retrospective` is persisted and echoed; submit-for-review is freeze- but not custody-gated — `routes/referrals.py:102`, `serializers.py:166`
- **§3.5** — the referral-`PENDING_UR` condition is a rung-10 `ERR_INVALID_STATE`; the review's own status is blamed first — `routes/referrals.py:145-149`
- **§3.5** — `information_text` is a required string that is **not persisted** — `routes/referrals.py:185-196`
- **§3.5** — peer-decide does not re-check the referral at rung 10 — `routes/referrals.py:240-250`
- **§3.6** — `required_escort_level`/`lead_minutes` persisted; create is not custody-gated; all five transitions return the **trip** — `routes/transport.py:74-85`
- **§3.6** — `SPECIALTY_OFFSITE` charge carries a null `source_sick_call_id` and is not written back — `routes/transport.py:176`
- **§3.6** — cancel bumps the referral only when it was `SCHEDULED` — `routes/transport.py:206-208`
- **§3.7** — ad-hoc charge's `source_sick_call_id` → rung-4 `ERR_RECORD_NOT_FOUND`, cross-inmate allowed, linked slip unmodified — `routes/trust.py:20`
- **§3.7** — deposit `amount_cents` unbounded (zero/negative accepted); `memo` → `""`; neither freeze- nor custody-gated; off-domain `entry_type` → `ERR_INVALID_ENUM` before the DEPOSIT-only `ERR_VALIDATION` — `routes/trust.py:63-83`
- **§3.8** — `subject_copay_charge_id` → rung-4 404, cross-inmate allowed; filing exempt from freeze **and** custody — `routes/grievances.py:27`
- **§3.8** — accept/escalate/remand/close all use rung-9 `ERR_INVALID_STATE`; accept never moves `stage` — `routes/grievances.py:99,153-158,188-192,213`
- **§3.8** — remand recomputes `response_due_at` but does **not** reset `stage_entered_at` — `routes/grievances.py:200-204`
- **§3.8** — withdraw/close leave `stage`, `stage_entered_at`, `response_due_at` untouched — `routes/grievances.py:216-232`
- **§3.9** — finalize is rung-9 gated, recomputes against the **stored** `planned_release_at`, does not re-run the lead-time test; neither freeze- nor custody-gated — `routes/release.py:71-86`
- **§3.9** — release returns **200 with the updated inmate**; all `FINALIZED` plans execute; DRAFT/EXECUTED/VOIDED plans untouched — `routes/inmates.py:78-79`, `cascades.py:123-128`
- **§3.9** — records-freeze/unfreeze idempotence failures are rung-9 `ERR_INVALID_STATE`; no payload; not custody-gated — `routes/inmates.py:107,119-125`
- **§3.9** — corrective-action attach is a legal **self-loop** from `CORRECTIVE_ACTIONS_ISSUED`; array elements carry only `action_text` + `recorded_at` — `routes/release.py:110-121`

### Categories checked and found ALREADY correctly pinned (no change needed)
- **Boundary edges** — all thirteen verified byte-for-byte against the code: strict-after for screening overdue / SLA / UR turnaround / lapse+grace / `closed_late` / `completed_late`; equality-accepted for transport lead time, cancel cutoff, release-plan lead; closed grievance filing/escalation and 48h peer-review windows; strict-both-parts indigency; **closed** medication date spans vs **half-open** 240-minute transport slots; the −30/+60/+120 dose-window ladder.
- **404-vs-validation routing order** and left-to-right nested resolution (§2.10) — matches `ladder.py` registration order exactly.
- **Rung 8's intra-rung sub-order** (required → type/range → enum) already correct; only the JSON-object pre-step was added.
- **Pagination defaults/bounds and envelope field names** (10 / 1–100 / 0, `limit`/`offset`/`total_count`/`has_more`) — already exact.
- **Freeze-gate scope** — endpoint-for-endpoint identical apart from the sick-call-close mismatch above; the 29 gated endpoints matched.
- **Both conservation invariants**, the six-step co-pay order, the two adherence variants, the double-rounding facility index, and the transport lead-time three-input formula — already uniquely pinned.
- **Serializer projections** — all 15 entities' field lists already recoverable from §3 prose; only the general projection rule, `retrospective`/`severity` and the MAR-row initial nulls were missing.

**Orchestrator independent verification:** `PRD_COMPLETED.md` present (466 lines / 120,462 chars vs PRD.md 458 / 101,792); heading count unchanged 27 → 27 and table-row count unchanged 105 → 105 (no section added, no endpoint/error table row lost); `PRD_FINALIZED.md` correctly absent (Step 8 skipped); 8 `results.*.json` rounds retained in `workspace/implementation/`.

---

# PIPELINE COMPLETE — Steps 1–9 (Step 8 correctly skipped)

Final state: **105/105 tests passing on all 8 stability-sweep rounds, zero Step-7 fixes of any kind.**
