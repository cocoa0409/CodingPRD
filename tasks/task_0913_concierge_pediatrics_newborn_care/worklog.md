# Worklog — task_0913_concierge_pediatrics_newborn_care

Scenario (verbatim): 913. Concierge Pediatrics & Newborn Care: membership & panel, well-visit & immunization schedule, 24/7 access & telehealth, lactation & sleep consult, school/camp form, sick-visit & after-hours, sibling/family plan, insurance-vs-membership split

Difficulty target: **beyond-Expert** (user request: "generate task hard than expert level!")

## Step 1: Create task directory — 2026-08-03T00:00:00.000Z

Created `tasks/task_0913_concierge_pediatrics_newborn_care/` and `workspace/`. Index 0913 = max existing (0912) + 1.

## Step 3: Copy INSTRUCTION.md — 2026-08-03T00:00:00.000Z

Copied `./INSTRUCTION.md` → `tasks/task_0913_concierge_pediatrics_newborn_care/workspace/INSTRUCTION.md`. (Run early; no dependency on Step 2.)

## Step 2: Generate scaffold — 2026-08-03T00:00:00.000Z

All three scaffold artifacts are written and verified.

### Files

- `SCAFFOLD.yaml` (§1.0–§1.7)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (§1.8)
- `SCAFFOLD_CORNER_DESIGN.yaml` (§1.9)

### Density report

| Dimension | Value |
|---|---|
| Entities | **15** |
| Endpoints | **61** (flat topology, all under `/peds`) |
| State machines | **11** |
| Non-linear SMs | **6** — Encounter (parallel `clinical_status` × `billing_status`), Membership (ACTIVE↔SUSPENDED cycle), FormRequest (PENDING↔BLOCKED cycle), EntitlementGrant (OPEN↔EXHAUSTED cycle), ImmunizationDose (VALID↔INVALID cycle), ConsultBooking (capped SCHEDULED self-loop, max 2), plus ServiceLine branching with divergent per-route side effects |
| Calculations | **14**, of which **4 dual-variant**: `membership_cycle_proration` (enrollment vs cancellation proration), `service_line_financial_split` (insurance / membership / patient routes), `immunization_dose_validity` (age rung vs interval rung), `after_hours_surcharge` (weekday window vs full-day) |
| Error codes | **30** |
| Validations | **38** arranged in a **17-rung** explicit priority ladder (`validation_priority_ladder` block) |
| OCC rules | **3** — 2 on `Family.version` (enroll, cancel), 1 on `InsurancePolicy.version` (adjudicate) |
| Conservation invariants | **3** — entitlement units (`available+booked+consumed == granted`), `Physician.weighted_occupancy`, `InsurancePolicy.deductible_met_cents` |
| Max cascade depth | **4 causal hops** ×2 from different triggers: cancel → Physician occupancy → PanelWaitlistEntry PROMOTED → new Membership → grants/well-visits/invoice; and dose invalidate → later dose re-index → Child completeness → FormRequest BLOCKED |
| Declared constants | **38** top-level in `domain_constants` + per-calculation `constants:` blocks. Every ALL_CAPS token in the file that isn't an enum member or error id has an explicit value (audited by script; 0 undeclared) |
| §1.8 instances | 22 across all 9 rule_ids (≥2 each) |
| §1.9 instances | 75 across all 9 guide sections (63 with full recipes, 12 `excluded_because` stubs) |

### Verification

- `yaml.safe_load` **OK on all three files** (fixed two known offenders: bare `foo?` tokens in `input:` flow sequences, and unquoted `$.data[0].x` / `errors[ERR_X]` brackets nested in flow collections).
- `scaffold_lint.py` verdict, verbatim:
```
Coverage
  §1.5 endpoints declared:    61
  §1.1 entities declared:     15
  §1.8 instances scanned:     22
  §1.9 instances scanned:     63
  Calls scanned (§1.8+§1.9):  900

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```
- All 28 FKs reverse-reachable; 97 instance names unique across both design files; 0 unresolved `grounds:` refs; all 12 stubs point at real §1.8 instances; neither design key appears in SCAFFOLD.yaml.
- Every formula-derived assertion literal was computed in Python before being written (invoice ladder 76066 vs the rejected 76067; cap waterfall 16066 → 40000/20000/0; coinsurance `round_half_up(4230×0.15)=635`; prorations 10323/14667/26667/18133/1333; all immunization ages/intervals; all milestone window dates; all weekday/holiday classifications).

### Notable seams mined

Immunization dose validity with a 4-day grace and series-shifting on invalidation; well-visit periodicity with inclusive open/close boundaries plus a 30-day miss-grace tail (so DELAYED is reachable); age-dependent weighted panel slots where the *same* enrollment is rejected in June and accepted at exact equality in July; sibling ladder pinned to enrollment sequence with a reverse-order family-cap waterfall; entitlement overage fall-through; insurance-vs-membership split with blocked balance billing; after-hours surcharge with three window variants and a top-tier waiver; form issuance gate that produces a BLOCKED state rather than an error; telehealth licensure + modality prohibition; segregation of duties on submit-vs-adjudicate.

### Orchestrator's independent verification

- `yaml.safe_load` re-confirmed on all three files (2583 / 2002 / 3601 lines).
- Structure re-counted from parsed YAML: entities 15, endpoints 61, state_machines 11, calculations 14, errors 30, validations 38.
- Design instances re-counted: difficulty 22 (0 stubs), corner 75 (12 stubs); 97/97 names unique.
- Independent ALL_CAPS constant sweep: **50 declared constants, 0 genuinely undeclared.** 25 constant-shaped tokens found; the only 2 not in the declared set are `MIN_AGE_NOT_MET` / `MIN_INTERVAL_NOT_MET`, which are dose-invalidation reason-code enum members (regex false positives on the `MIN_*` pattern), not constants.

## Step 4: Generate PRD — 2026-08-03T00:00:00.000Z

PRD generated at `workspace/PRD.md` (457 lines, ~111 KB), authored in eight bounded Write/Edit calls.

### Endpoint count
**Documented: 61. Scaffold: 61. Match confirmed** — verified programmatically as an exact set equality of (method, path) pairs between the §4 table and `endpoints[]`, with per-row role-list equality also checked (0 mismatches).

### Structure
- §2 has 11 subsections (2.1 identity/RBAC, 2.2 verbatim envelope, 2.3 pagination + every list filter, 2.4 logical clock + datetime/date rendering, 2.5 common properties, 2.6 not-found routing, 2.7 the full 17-rung ladder, 2.8 OCC, 2.9 money/weights/rounding, 2.10 conservation, 2.11 status codes).
- §3 has 9 subsections organised by lifecycle: practice setup → enrolment/panel → invoice cycle → cancellation chain → preventive care → encounters → billing split → benefit pools → forms.

### Hard contract reports

```
Field coverage check:
- entities[].fields: 118 required, 118 present, 0 missing
- endpoints[].request_body: 50 required, 50 present, 0 missing
- endpoints[].query_params: 26 required, 26 present, 0 missing
- endpoints[].path_params: 15 required, 15 present, 0 missing
- endpoints[].output keys: 7 required, 7 present, 0 missing
- derived/common (invoice line keys, id/created_at/updated_at/version, meta): 10 required, 10 present, 0 missing
Status: PASS
```

```
Rule coverage check:
- validations[] with priority: 38 checked, 38 expressed in prose (as the 17-rung ladder in §2.7), 0 missing
- concurrency_rules[] OCC rejections: 3 checked, 3 expressed (write_endpoint + expected_family_version / expected_policy_version + ERR_STALE_VERSION + 412 all named), 0 missing
- state_machines[].transitions: 48 checked across 11 machines, 48 fully expressed, 0 missing
- calculations[]: 14 checked, 14 fully expressed (incl. all 9 declared variants), 0 missing
- validations[] conditions: 38 checked, 38 matchable to error_id in prose; all 30 error ids appear in §1–§4 narrative
- endpoints[].side_effects / applies_to: 61 endpoints checked, all side-effect sets and applies_to scopes expressed
- entities[].fields[] structured content: 118 checked, 118 reconstructible (defaults, initial values, enum member sets, computed derivations)
- sibling-branch symmetry: 6 groups checked (3 financial-split routes, 2 proration shapes, 2 after-hours shapes, 2 immunization rungs, 3 form-gate rungs, 3 cancel-source states), 0 asymmetric
Status: PASS
```

```
Path purity check (§3 only):
- backtick tokens scanned: 939
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

### Boundary semantics stated explicitly
Immunization 4-day grace (inclusive, "exactly 4 early passes, 5 fails"); 30-day due lag (inclusive); well-visit window generation (inclusive at `window_close_date >= start_date`); punctuality (both boundaries belong to `ON_SCHEDULE`); 30-day miss grace (strict); 90-day waitlist TTL (strict); panel admission (inclusive at equality, compared on values ×10); consult buffer (half-open + 15-min trailing pad, non-colliding at equality); encounter interval (closed, touching endpoints collide); after-hours 18:00 inclusive / 08:00 exclusive; form recency window (both bounds inclusive); `sla_met` inclusive at equality; proration day-counting inclusive on both endpoints; activation window `cycle_start_date`–`cycle_end_date` inclusive.

Three conservation invariants (benefit-pool, deductible, invoice) are stated in §2.10 with their forward and compensating actions. §2.2 was verified byte-identical to `section-2.2-response-structure.md`. Neither design yaml was opened; all worked examples come from `SCAFFOLD.yaml`'s own calculation blocks. PRD.md ends at the §5 table with no audit footer.

### Orchestrator's independent verification
- 457 lines / 111,289 chars.
- All 61 scaffold endpoint paths found verbatim in PRD.md (0 missing).
- All 30 scaffold error codes found in PRD.md (0 missing).

## Step 5: Generate unit tests — 2026-08-03T00:00:00.000Z

Test infrastructure and suite are complete.

### What was generated

**`test_helpers/`** (9 files, ~1,800 lines)
- `types.py` — 22 status/enum classes + 15 entity TypedDicts (every entity carries `common_fields: true`, so all four system fields are declared)
- `api_client.py` — 58 endpoint methods, one per PRD §4 row, all under `/peds`
- `api_errors.py` — 30 error ids + HTTP map, registered with the framework
- `assertions.py` — per-entity assertions, the three conservation checkers (`assert_grant_conservation`, `assert_invoice_conservation`), and **semantic temporal comparison**: `parse_instant` / `parse_day` / `assert_instant_equals` / `assert_date_equals` parse both sides and compare instants (or dates), so a server rendering `...000Z` against a caller's plain `...Z` cannot produce a false failure
- `constants.py`, `factories.py`, `test_users.py` (per-instance `make_physician_headers` / `make_parent_headers` builders for the two `entity_backed` roles, plus `make_billing_headers` for segregation-of-duties), `fixtures.py` (`setup_practice` → `setup_pending_membership` → `setup_active_membership` → `setup_insured_active_membership` → `setup_routed_insurance_line`, plus ~40 domain helpers)

**`test_suite/`** — `conftest.py` + 11 domain-named files, **107 `def test_` functions**.

### Coverage

- **Queue A: 22 / 22** instances produced tests — 44 tests, every instance covered by exactly 2.
- **Queue B: 63 / 63** non-stub instances produced tests — 63 tests, one each. The 12 `excluded_because` stubs were verified to cross-reference real difficulty instances and were not translated.
- **Zero instances skipped.** No `skip` / `skipif` / `xfail` anywhere.

### Verification run

- Every test carries exactly one `Design:` line; all 107 tags resolve to real non-stub instances (no untagged, dual-tagged, or stub-tagged tests).
- All **219 quoted PRD fragments** survive a literal whitespace-normalized match against `workspace/PRD.md`.
- `pyflakes` clean; `pytest --collect-only` collects 107 tests.

### One assertion deliberately relaxed

`corner_adjudicating_a_membership_routed_line_returns_route_not_adjudicable` expects `ERR_ROUTE_NOT_ADJUDICABLE`, but the line under test is a membership-covered line born `SETTLED`, and PRD §2.7 puts the state rung (10, `ERR_INVALID_STATE`) **above** the route rung (12). A PRD-only implementer following the pinned ladder returns 409, not 422. Per the skill's `error-precedence` silence pattern I used `validate_error_is_one_of([ERR_ROUTE_NOT_ADJUDICABLE, ERR_INVALID_STATE])` and kept the full unchanged-line assertions, so the instance stays covered without pinning a precedence the PRD contradicts.

### Two design-file assertions corrected against the PRD

`panel_weighted_occupancy_conserved_across_enroll_and_cancel` and `membership_cancel_frees_weight_promotes_waitlist_and_seeds_new_membership` both assert a surviving membership reads `ACTIVE`, but neither recipe issues or pays an invoice — and PRD §3.3 says "There is no other route to activation". Those tests assert `PENDING_ACTIVATION`, which is what the PRD uniquely derives; the panel-occupancy figures are unaffected since `PENDING_ACTIVATION` already occupies slot weight.

## Step 6: Generate implementation — 2026-08-03T00:00:00.000Z

Implementation complete at `workspace/implementation/`.

### Completeness gate — PASSES
`scaffold endpoints: 61 / registered routes: 61 / MISSING: 0 / EXTRA: 0`. Verified by diffing `endpoints[]` in SCAFFOLD.yaml against a booted `app.url_map` (path templates normalized). Also lint-clean under pyflakes; boots via `start.sh` in ~0.5 s on `0.0.0.0:$PORT`, foreground `exec`, guarded pip install; fresh process starts with an empty store and the clock back at `2026-05-01T00:00:00Z` (no seeding anywhere, no files/DB written).

### Two adjudications

**1. Timestamp rendering — one rule for every datetime.** PRD §2.4 is explicit, so I applied it uniformly with no server/caller split: *every* emitted datetime renders as ISO 8601 UTC with exactly three fractional digits and a trailing `Z`. Inbound datetimes are parsed with optional fractional digits and **normalized to millisecond resolution at ingest** (`validate.req_datetime` → `timeutil.normalize_datetime`), so a caller's `2026-03-01T00:00:00Z` round-trips as `2026-03-01T00:00:00.000Z` — byte-identical to a server stamp. Derived stamps inherit the same rule (`ends_at = started_at + 30min`, `due_at = requested_at + form_sla_hours`, `current_utc`). All datetimes are stored as naive UTC `datetime` and rendered only in `serialize.py`. Calendar-date fields (`date_of_birth`, `start_date`, `window_*_date`, `issued_date`, …) are bare `YYYY-MM-DD`. `created_at`/`updated_at` come from the logical clock verbatim (never wall clock); strictly-increasing ordering is carried by a hidden `_seq` counter, never by inflating `created_at`.

**2. Enum-membership routing — every enum field goes to `ERR_INVALID_ENUM`.** The catalogue defines `ERR_INVALID_ENUM` (400) as "an enum-typed field carries a value outside its declared member set", and §2.7 rung 4 extends it to filters. So: a field is type-checked at priority 9 (non-string → `ERR_VALIDATION`), then *any* string outside the member set → `ERR_INVALID_ENUM` — applied to all of `tier`, `status` (policy create), `form_type`, `consult_type`, `modality`, `encounter_type`, `vaccine_code`, and to **every** list filter (`status` on all 8 collections, `benefit_type`, `route`, `validity`, `clinical_status`, `billing_status`, `milestone_code`) regardless of whether the PRD names it. No enum field is left on generic `ERR_VALIDATION`. Verified: `?status=BOGUS&limit=0` returns `ERR_INVALID_ENUM` (p10 before p11).

### 17-rung ladder mechanism
The ladder is **source-line order inside each handler**, with a `# RUNG n pXX` comment on each check, so precedence is readable and re-orderable by a later fix pass. Rungs 1/2 are `auth.begin(roles)`; rung 3 is inline path lookup with the collection-specific 404; rung 4 is grouped strictly as *all* presence/type checks → *all* enum checks → *all* range checks; rung 5 is date parse then `date_range()`; rungs 6–17 follow. Errors raise `ApiError` immediately, so the first failing rung wins and nothing is persisted.

One deliberate deviation, commented in `routes_billing.adjudicate_line`: rung 12 (`ERR_ROUTE_NOT_ADJUDICABLE`) is evaluated **ahead of** rung 10 for non-insurance lines. Strict ordering makes rung 12 unreachable (membership/patient lines are born `SETTLED`, so rung 10 always fires first), yet PRD §3.7 states such a line "is refused with `ERR_ROUTE_NOT_ADJUDICABLE`". Insurance-routed lines keep the exact ladder order (SoD → OCC → state → policy state). OCC is skipped when the line names no policy, so it can't pre-empt the route error.

### Parallel state axes
**Encounter** carries `clinical_status` × `billing_status` as two independent stored fields. `complete-clinical` never reads or writes `billing_status`; `submit-billing` never reads or writes `clinical_status` (both are asserted in `routes_encounters.py` comments and covered by smoke tests: a billing-closed encounter still completes clinically, and billing submits on a clinically-incomplete encounter). Only `cancel` touches both, and its precondition is a conjunction over the two axes. The billing axis additionally **bubbles up from its ServiceLine children** (`svc_line.bubble_billing_axis`) — firing inside `submit-billing` when every created line is born `SETTLED`, and inside `settle` when the last insurance line closes.

### 4-hop cancellation cascade (CASCADE A, `svc_membership.cancel_membership`)
Hop 0 direct write (status/effective date/`Family.version` +1) → seven **direct fan-out legs** (ladder rerun, DRAFT invoice rebuild, grants→`EXPIRED`, scheduled bookings→`CANCELLED`, open well visits→`CANCELLED`, PENDING forms→`BLOCKED`, SCHEDULED encounters→`CANCELLED`/`BILLING_VOID` with their lines voided) → hop 1 panel weight released (occupancy is computed live, so it falls automatically) → hop 2 promotion selector → hop 3 new membership + promoted family's `version` +1 → hop 4 grants, well visits, DRAFT invoice for the promoted household.

Legs that deliberately do **not** fire: grants expire *before* bookings cancel, so the release can never flip an `EXPIRED` pool back to `OPEN`; `consumed_count` is preserved while `booked_count` drains to 0; `CLINICALLY_COMPLETE` encounters and their ServiceLines are untouched; `SETTLED` lines are never voided; `COMPLETED`/`MISSED` well visits and `ISSUED` forms are untouched; `ISSUED`/`PAID` invoices are frozen; exactly one waitlist entry is promoted per cancellation and earlier entries that don't fit are skipped (stay `WAITING`); when nothing fits, hops 3–4 do not fire at all.

### Modules (4031 lines total)
`routes_core.py` 355, `serialize.py` 307, `routes_membership.py` 306, `routes_benefits.py` 283, `routes_billing.py` 268, `calc.py` 257, `routes_clinical.py` 248, `routes_encounters.py` 246, `svc_membership.py` 204, `constants.py` 191, `validate.py` 181, `routes_forms.py` 153, `svc_line.py` 131, `svc_immunization.py` 127, `store.py` 112, `timeutil.py` 111, `svc_entitlement.py` 105, `svc_invoice.py` 82, `auth.py` 82, `errors.py` 76, `app.py` 69, `envelope.py` 41, `svc_booking.py` 38, `svc_form.py` 37, `listing.py` 10, `start.sh` 10, `requirements.txt` 1.

### Verification
Five smoke suites (~250 assertions) all pass, pinning the PRD's own worked numbers: invoice round-per-line-then-sum 76066 (vs the rejected 76067) and the reversed cap waterfall to exactly 60000; the insurance split 9770/4230/635/3595/10405/4000; both immunization worked examples plus a CASCADE B re-evaluation that rehabilitates `INVALID → VALID`; the 4.5-cap age-weight admission test; the 15-minute consult buffer accepted at equality vs. rejected one minute closer; closed-interval encounter collision at touching endpoints; the waitlist 90-day TTL boundary (survives day 90, expires day 91); benefit-pool conservation after every request; deductible reversal on encounter cancel; and full RBAC/ownership/404-routing coverage.

Two judgement calls worth flagging for a later fix pass: (a) **list endpoints scope rows to the caller's household when the role is `Parent`** (no 403) — the PRD's ownership rung names a "target resource" and is silent on lists; (b) **version bumps are once-per-row-per-request**, except the policy version on encounter-cancel voiding, which the scaffold counts per adjudicated line, and sibling memberships, which bump only when the ladder actually changes one of their three fields.

### Orchestrator's independent verification (Steps 5+6)
- `def test_` count = 107 across 11 files; `Design:` tags = 44 Difficulty + 63 Corner = 107 (exactly one per test).
- No `skip`/`xfail`/`skipif` markers anywhere (sole grep hit is the domain word "skips" inside a test *name*).
- No persistence smells in `implementation/`: 0 hits for `sqlite|json.dump|pickle|open(|/tmp|shelve`.
- Booted the app independently: 61 rules / 61 method-path pairs.
- `start.sh` confirmed: guarded pip install, `exec python3 app.py` in foreground.

## Step 7: Run tests and iterate — 2026-08-03T00:00:00.000Z

All verification complete. The sweep is genuinely clean on the first iteration — no fixes or deletions were needed.

**Iterations run: 1.** The baseline 8-round sweep came back 107/107 on every round, so the diagnostic protocol (STEP 0–3) never had a failing test to operate on. Union of failures across all 8 rounds: **empty**.

```
round 1..8:  total=107  passed=107  failed=0  errors=0  skipped=0
```

### The five clean-sweep verification checks

| # | Check | Result |
|---|---|---|
| 1 | All 8 `results.N.json` parse and each carries 107 individual test rows (not just an aggregate counter) | **PASS** — 107 rows in each of the 8 files |
| 2 | Set of test names identical across all 8 rounds | **PASS** — all 8 sets equal, 107 unique names |
| 3 | `grep -c "def test_" test_suite/*.py` totals 107 and equals collected count | **PASS** — 107 source defs; runner collected 107; the two name sets are set-equal (no extras, no omissions) |
| 4 | No `skip`/`xfail`/`skipif` markers in `test_suite/` or `test_helpers/` | **PASS** — zero hits for `pytest.mark.skip`, `pytest.mark.xfail`, `skipif`, `pytest.skip(`. (The earlier loose grep matched only a test *name* containing "skips" and the word "skipped" in a docstring — neither is a marker.) |
| 5 | `grep -rn "sqlite\|json.dump\|pickle\|open(\|/tmp\|shelve"` over `implementation/` is empty | **PASS** — zero hits; `store.py` is pure in-memory Python dicts, `reset()` on construction, no seeding at import or startup |

### Additional anti-false-clean due diligence

- **No vacuous tests** — all 107 test bodies contain assertion constructs (`assert` / `validate_*` / `assert_*`); zero with none.
- **Real execution** — per-test durations 0.557s–1.269s, sum 109.2s against 111.2s wall; no zero-duration rows.
- **Per-test-server isolation genuinely in force** — proven conclusively rather than by log-scraping: ~69 call sites across the suite invoke the practice-setup helpers, each creating a `PLUS` plan tier. PRD §3.1 refuses a duplicate tier with `ERR_DUPLICATE_WAITLIST_ENTRY`. If any state survived between tests, every test after the first would fail at setup. All 107 pass in all 8 rounds, so state is wiped per test.
- **No mass-kill / saturation** — the `143` in each round log is a *line number* in `lifecycle:stop:143`, not an exit code; the single `Killed` right after test #1 is the documented pre-boot-server swap artifact. Every round wrote a complete `results.json`.
- **Endpoint completeness** — PRD endpoint table has 61 rows; implementation registers 61 routes.

### Changes made

- **Tests deleted:** none.
- **Fixes to `test_helpers/`:** none.
- **Fixes to `test_suite/`:** none.
- **Fixes to `implementation/`:** none.

### Note on the four flagged friction points

None produced a failure, and the corresponding tests pass in all 8 rounds:
- **Adjudication ladder precedence** — `test_a_membership_routed_line_can_never_be_adjudicated` passes; Step 5's relaxation to `validate_error_is_one_of([ERR_ROUTE_NOT_ADJUDICABLE, ERR_INVALID_STATE])` and Step 6's rung-12-before-rung-10 ordering for non-insurance lines are compatible as predicted.
- **Membership activation state** — `test_paying_the_cycle_invoice_activates_the_pending_membership` and `test_pending_membership_refuses_consult_booking_until_the_invoice_is_paid` both pass, confirming the `PENDING_ACTIVATION` reading of PRD §3.3 ("There is no other route to activation").
- **Parent-role list scoping** — `test_a_parent_may_not_read_another_households_child` and the pagination test pass; the household-scoping choice for lists was not contradicted.
- **Version-bump cardinality and timestamp rendering** — `test_household_version_advances_on_enrol_and_cancel_only` and `test_voiding_an_adjudicated_line_gives_the_deductible_back` pass. Step 6 normalizes all inbound datetimes to millisecond resolution at ingest and Step 5 compares timestamps semantically, so the two are mutually immune here — this task does *not* reproduce the `.000Z`-vs-plain-`Z` defect seen in 1060/1076/1088/1093.

### Orchestrator's independent re-verification of the clean sweep

Re-checked directly rather than trusting the subagent's report:
- 8 `results.*.json` present; each parses with **107 individual rows**, 107 passed, aggregate `107/107`.
- **Test-name sets identical across all 8 rounds**; 107 unique names.
- `pytest.mark.skip|pytest.mark.xfail|skipif|pytest.skip(` across `test_suite/` + `test_helpers/`: **0 hits**.
- Tests whose body contains no assertion construct: **0**.

## Step 8: Finalize PRD — SKIPPED — 2026-08-03T00:00:00.000Z

**Skip condition met.** Step 7 exited on the first 8-round sweep with 0 deletions, 0 `test_suite/` fixes, 0 `test_helpers/` fixes, and 0 `implementation/` fixes — zero iterations beyond the baseline. `PRD.md` already determined every behavior the implementation exhibits at every site the test suite exercised, so there is no `<step_7_diff>` to drive a finalization pass and no `PRD_FINALIZED.md` is produced. Step 9 therefore starts from `PRD.md` and is the sole completeness pass.

## Step 9: Complete PRD — 2026-08-03T00:00:00.000Z

Full audit of all 61 endpoints, 11 state machines, 14 calculations and 30 error codes against `implementation/`, with 40 minimal in-paragraph edits applied to `PRD_COMPLETED.md`.

### Counts

| | |
|---|---|
| `PRD.md` | 457 lines / 111,704 chars |
| `PRD_COMPLETED.md` | 459 lines / 127,742 chars (**+2 lines, +16,038 chars**) |
| Ambiguity-pins | **33** |
| Mismatch-revisions | **7** |

Section headers and both tables (61 endpoint rows, 30 error rows) are byte-identical; no new sections were added.

### Changes

- §2.2 — insert — ambiguity — `api_request_id` is `req_` + exactly 20 upper-case alphanumerics; `api_request_timestamp` is read from the logical clock, not wall clock — `envelope.py:13-17`
- §2.2 — insert — ambiguity — pagination `meta` keys absent from single-object responses (only the two keys) — `envelope.py:20-32`
- §2.3 — **revise** — **mismatch** — "no secondary tie-break is needed … guarantees strictly increasing `created_at`" is false; ties break by a hidden store-wide write-order counter, never `id`, and that rule governs every `created_at` ordering in §3.2/3.3/3.4/3.5/3.7 — `store.py:39-43,72,88-91`
- §2.3 — insert — ambiguity — `limit`/`offset` that are not base-10 integers → `ERR_VALIDATION`; empty string falls back to default — `validate.py:148-166`
- §2.3 — insert — ambiguity — filters absent/empty impose nothing; non-enum filters are exact string compares yielding an empty page (not 404/400); `cycle_start_date` compared against the rendered `YYYY-MM-DD` — `validate.py:169-173`, `routes_billing.py:195-199`
- §2.3 — insert — ambiguity — `membership_year_index` is the one numeric filter and must parse as an integer → `ERR_VALIDATION`; enum-filter routing binds every enum filter whether or not §2.7 names it — `routes_benefits.py:47-53`, `validate.py:176-181`
- §2.4 — insert — ambiguity — clock response `data` carries `current_utc` only, with none of the common four — `routes_core.py:50`
- §2.4 — insert — ambiguity — both sweeps run on every accepted call including a standstill; well visits swept before waitlist entries — `routes_core.py:29-48`
- §2.4 — insert — ambiguity — accepted inbound datetime spellings (1–9 fractional digits truncated to ms, `T`/`t`, `Z`/`z`/`±00:00`); any other zone fails to parse — `timeutil.py:21-45,81-85`
- §2.5 — **revise** — **mismatch** — `version` increments **at most once per row per request**, and a row created by the request stays at 1 however much later steps rewrite it; `updated_at` refreshes on every write regardless — `store.py:61-103`
- §2.5 — insert — ambiguity — the two exceptions (policy version once per *voided adjudicated line*; sibling ladder writes only on real change) plus the counter-case (DRAFT invoice rebuild is unconditional) — `store.py:106-112`, `svc_line.py:127-132`, `svc_membership.py:37-46`, `svc_invoice.py:63-69`
- §2.5 — insert — ambiguity — payload completeness: exactly the common four plus the narrative's named fields, unset values emitted as `null` — `serialize.py:8-307`
- §2.6 — insert — ambiguity — no route carries more than one path identifier; unknown path or unsupported method → `ERR_RESOURCE_NOT_FOUND` 404 — `app.py:41-50`
- §2.7 r4 — insert — ambiguity — strings must be non-empty, booleans rejected as integers, arrays non-empty with typed members (`licensed_state_codes` = two upper-case chars), unknown fields ignored, absent/malformed body screened as `{}` — `validate.py:22-87`, `routes_core.py:118-122`
- §2.7 r6 — insert — ambiguity — within-rung resolution order pinned per endpoint (notably consult-booking resolves `consultant_physician_id` **before** `membership_id`) — `routes_membership.py:37-45`, `routes_benefits.py:105-110`
- §2.7 r7 — insert — ambiguity — list endpoints scope a `Parent` to their household (incl. `total_count`) instead of 403; plan/physician reads never carry the rung; the caller's own `X-User-ID` is never resolved to a 404 — `auth.py:73-77`, all `routes_*.py` list handlers
- §2.7 r9 — insert — ambiguity — OCC skipped when the line names no policy, so such a line can never answer `ERR_STALE_VERSION` — `routes_billing.py:95-97`
- §2.7 r10 — insert — ambiguity — the row's own status is evaluated before the invoice-standing test on suspend/reinstate — `routes_membership.py:169-172,187-190`
- §2.7 r12 — **revise** — **mismatch** — route eligibility is evaluated **out of numeric order, ahead of rungs 10 and 11**, because otherwise it would be unreachable; insurance lines keep the declared order — `routes_billing.py:99-110`
- §3.1 — insert — ambiguity — panel summary is a computed projection carrying six fields and none of the common four; `panel_slot_cap` echoed as supplied — `routes_core.py:173-183`
- §3.2 — insert — ambiguity — ladder `created_at` key resolves by write order; a rerun writes to a sibling only when a ladder field actually changes — `svc_membership.py:31-46`
- §3.2 — insert — ambiguity — enrolment fan-out order (ladder → grants, lactation first → well visits → billing) — `svc_membership.py:87-91`, `svc_entitlement.py:41-43`
- §3.4 — insert — ambiguity — grants expire **before** bookings release, so a release can never reopen an `EXPIRED` pool; `released_count`/`overage_count` still move — `svc_membership.py:122-132`, `svc_entitlement.py:87-96`
- §3.4 — insert — ambiguity — the encounter leg voids `ROUTED`/`ADJUDICATED` lines with the deductible reversal, and forces `BILLING_VOID` from any current billing status incl. `BILLING_CLOSED` — `svc_membership.py:155-165`, `svc_line.py:118-132`
- §3.4 — insert — ambiguity — hop 3 skips the version token, duplicate-membership and panel-capacity rungs; same-family promotion still advances that family's version by exactly 1 — `svc_membership.py:195-204`
- §3.5 — insert — ambiguity — well-visit scheduling: visit status tested first; non-`PENDING_ACTIVATION`/`ACTIVE` membership → `ERR_INVALID_STATE` (not `ERR_MEMBERSHIP_NOT_ACTIVE`); past `scheduled_date` → `ERR_INVALID_DATE_RANGE` — `routes_clinical.py:90-101`
- §3.5 — insert — ambiguity — a dose beyond position 1 with a null `prior_valid_dose_id` (all earlier valid doses share its date) gets `interval_days_since_prior` 0 — `svc_immunization.py:47-50`
- §3.5 — insert — **mismatch** — recording a dose re-runs the verdict across the **whole** series (not only later doses), so a back-dated insert re-classifies later doses; the new dose still answers at version 1 — `routes_clinical.py:185`, `svc_immunization.py:20-100`
- §3.5 — insert — ambiguity — the dose-invalidation form-blocking leg is unconditional, keyed on `child_id` across all memberships, and does not re-run the §3.9 gate — `svc_immunization.py:103-113`
- §3.6 — insert — ambiguity — the after-hours ladder never consults `encounter_type` — `calc.py:159-179`
- §3.6 — insert — ambiguity — the primary line is written before the surcharge line, fixing set order and cancel-walk order — `routes_encounters.py:198-216`, `svc_line.py:98-101`
- §3.7 — insert — ambiguity — `submitted_by_user_id` is the acting caller on all three line sources, not just encounter submission — `svc_line.py:75`, `routes_clinical.py:143`, `routes_benefits.py:265`
- §3.7 — **revise** — **mismatch** — policy candidate ranking: "no tie-break needed" is false; the later-written policy wins at an identical `created_at` — `svc_line.py:22`
- §3.7 — insert — ambiguity — `patient_responsibility_override_cents` is never persisted or echoed; omitting it skips the ceiling check — `routes_billing.py:86,114-118`, `serialize.py:241-266`
- §3.7 — **revise** — **mismatch** — the five adjudication conditions are walked SoD → version → **route** → line status → policy status — `routes_billing.py:92-110`
- §3.7 — **revise** — **mismatch** — version check skipped when no policy is named — `routes_billing.py:95-97`
- §3.7 — **revise** — **mismatch** — the route condition is tested before the two status conditions, so a `SETTLED` non-insurance line draws `ERR_ROUTE_NOT_ADJUDICABLE`, not `ERR_INVALID_STATE` — `routes_billing.py:104-108`
- §3.8 — insert — ambiguity — a future `scheduled_end` on completion → `ERR_INVALID_STATE`, status tested first; completion does not require an `ACTIVE` membership — `routes_benefits.py:240-245`
- §3.8 — insert — ambiguity — overage completion leaves the grant row entirely unwritten (no `version`/`updated_at` move) — `svc_entitlement.py:79-84`
- §3.9 — insert — ambiguity — a recheck that leaves the request `BLOCKED` on the same reason still bumps `version` — `routes_forms.py:146-152`

**Boundary sweep result:** all 30+ `<=`/`<` comparison sites in the implementation (panel capacity at equality, slot-weight bands, 4-day immunization grace, 30-day due lag, well-visit window inclusivity, 30-day miss tail, 90-day waitlist TTL, after-hours 18:00/08:00 edges, closed encounter interval, half-open+15min booking buffer, form-gate 365-day window inclusive both ends, `sla_met` at equality, activation cycle bounds, inclusive covered-days) were already pinned uniquely by the source PRD and needed no edit.

### Orchestrator's independent verification
- `PRD_COMPLETED.md` present: 459 lines / 127,245 chars vs PRD.md 457 lines.
- All 61 endpoint paths and all 30 error codes still present (0 missing).
- Heading structure **byte-identical** to PRD.md (`diff` on all `^#` lines is empty) — confirms no new sections.
- 45 added/changed lines vs PRD.md — consistent with 40 in-paragraph edits.

## Pipeline complete — 2026-08-03T00:00:00.000Z

All 9 steps done (Step 8 correctly skipped). Final state: **107/107 tests passing on all 8 sweep rounds, 0 fixes, 0 deletions.**
