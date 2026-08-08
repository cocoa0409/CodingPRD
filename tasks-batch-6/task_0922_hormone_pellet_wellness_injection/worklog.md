# Worklog — task_0922_hormone_pellet_wellness_injection

Scenario (verbatim from user):
> 922. Hormone-Pellet & Wellness-Injection Clinic: consult & lab, pellet-insertion procedure & schedule, inventory (pellet/lot) & standing order, membership & series, follow-up lab & re-dose, adverse-event, self-pay/financing, recall

Difficulty target: **beyond-Expert** (user asked for "hard than expert level").

## Step 1: Create task directory — 2026-08-04T03:58:30.000Z

Created `tasks/task_0922_hormone_pellet_wellness_injection/` and `workspace/`. Host at launch: load 0.93 on 8 cores, no co-tenant pipeline.

## Step 3: Copy shared files — 2026-08-04T03:58:32.000Z

Copied `./INSTRUCTION.md` → `tasks/task_0922_hormone_pellet_wellness_injection/workspace/INSTRUCTION.md`. (Run early, out of order, since it has no dependency on Step 2.)

## Step 2: Generate scaffold — 2026-08-04T05:11:00.000Z

Subagent summary (verbatim):

All three scaffold artifacts are written to `/home/ubuntu/github/CodingPRD/tasks/task_0922_hormone_pellet_wellness_injection/` and pass every gate.

## Counts

| Dimension | Value |
|---|---|
| Entities | **16** (Patient, Provider, Protocol, ConsentRecord, Consult, LabPanel, PelletLot, StandingOrder, Procedure, PelletAllocation, Membership, SeriesPack, InjectionVisit, AdverseEvent, FinancingPlan, PatientNotification) |
| Endpoints | **72** (incl. `POST /clinic/_clock/set_current_utc`, default clock `2026-05-01T00:00:00Z`) |
| State-machine axes | **14**, of which **13 non-linear** (only `ConsentRecord.status` is linear). Procedure carries two independent axes on one row (`status` × `recall_status`); 6 axes are cyclic |
| Calculations | **19**, of which **7 have variant forks** |
| Error codes | **53** |
| Validation rungs | **39** (rung 9 = global standing-order write gate) |
| OCC rules | **3** (Patient/perform, Procedure/allocations, Membership/tier-change) |
| Conservation invariants | **3** (lot pellets, series entitlements, financing cents with two legs) |
| Cascade depth | **5** (lot recall: Lot → allocations → procedures → notifications → surveillance AEs); plus depth-4 severe-AE, protocol-publish and delinquency-default cascades |
| Declared constants | **75**, all with explicit numeric values |
| §1.8 | 9 rules / **26 instances** |
| §1.9 | 8 sections / **63 instances** (56 with recipes, 7 `excluded_because` stubs) |

## Self-check results

- **B — YAML lint**: `yaml.safe_load` on all three files → OK. Two known offenders were hit and fixed: bare `?` in `input: [limit?, …]` flow sequences (27 lines quoted), and nested `[` in `captures: { x: $.data[0].id }` / `grounds: [errors[…]]` (quoted).
- **C — No undeclared constants**: 0 unclassified ALL_CAPS tokens across all three files after subtracting the enum vocabulary and `ERR_*`. All unit conversions stated as formulas (`days_between`, `hours_between`, dose→pellet ladder, mg→cents price, per-line rounding order).
- **D — Reachability**: 0 enum values without a producer, 0 transitions referencing undeclared states, 0 forbidden concurrency vocabulary, 0 fuzzy selector adjectives, `created_at ASC` (never `id`) as FEFO tie-break. A `design_notes.reachability_audit` block documents 11 specific findings. Two real fixes made during the audit: `FACILITY_FEE_WAIVER_THRESHOLD_CENTS` was originally **mathematically unhittable** (150000 vs a 68000 max subtotal) and was retuned to **42625**, which an ESTRADIOL 100 mg procedure hits exactly; and rung 26 (post-insertion window) would have been unreachable behind rung 23 for same-hormone re-doses, so its reachable path is pinned as a **cross-hormone INITIAL** booking. Write-gate exclusions (Physician path, scheduling, allocation, data entry) are enumerated on rung 9 with the reason each keeps rungs 10–39 alive.
- **E — Consistency**: 72 endpoints, no duplicates; 0 errors referenced-but-uncatalogued and 0 catalogued-but-unreferenced; every error code now has at least one design instance; all 7 roles declare `identity:` and every endpoint role resolves; 36 FK fields all use the canonical `FK -> {Entity}.id` prefix; 89 instance names unique across both design files; 0 unbound `${var}`; 0 unresolved `grounds`; all `excluded_because` stubs cite a real §1.8 instance and carry no `test_recipe`.

`scaffold_lint.py` verdict (pasted verbatim above): **clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5**, over 820 scanned calls.

## Design notes worth carrying forward

- **Discount-costs-the-waiver trap**: a PLUS member's ESTRADIOL 100 mg procedure totals **45862** while a non-member's identical procedure totals **42625** — the 10 % discount drops the subtotal below the facility-fee waiver threshold. Fully deterministic, and it forces the implementer to honour the pinned evaluation order rather than "simplify" it.
- **Partial-pellet wastage splits an allocation row** (original id keeps the CONSUMED remainder, a new row at the same `allocation_rank` carries the WASTED quantity) — pinned explicitly after the audit found the split otherwise ambiguous.
- **One mutate-then-reject rung** (series expiry forfeits then raises `ERR_SERIES_EXPIRED`), scoped so the side effect fires exactly once and a second attempt is a clean no-write rejection.
- **Cross-patient blast radius**: a SEVERE adverse event on patient A suspends the standing order, which holds patient B's procedure, which returns B's reserved pellets to the FEFO pool — changing which lot a third patient draws.

**Orchestrator independent verification:** all 3 files `yaml.safe_load` clean (SCAFFOLD 200 KB / DIFFICULTY 134 KB / CORNER 158 KB); `endpoints` len = 72, `entities` len = 16, `errors` len = 53, `roles` len = 7, `calculations` len = 19, `domain_constants` len = 75. Independent ALL_CAPS suffix sweep (`_DAYS|_MINUTES|_HOURS|_LIMIT|_CAP|_MAX|_MIN|_BUFFER|_WINDOW|_THRESHOLD|_PCT|_FEE|_RATE|_CENTS|_MG|_COUNT|_SCORE|_PERCENT`) found 3 tokens not in the scalar-constant map: `ERR_SYMPTOM_SCORE_BELOW_THRESHOLD` (an error code) and `PELLET_LADDER_{ESTRADIOL,TESTOSTERONE}_MG` — both declared with list values at `SCAFFOLD.yaml:83-84`. **0 undeclared constants.**

## Step 4: Generate PRD — 2026-08-04T05:27:00.000Z

Subagent summary (verbatim):

PRD generated at `/home/ubuntu/github/CodingPRD/tasks/task_0922_hormone_pellet_wellness_injection/workspace/PRD.md` — 511 lines, ~18,100 words. Structure: §1 introduction (3 paragraphs), §2 with 11 domain-derived subsections, §3 with 9 workflow subsections, §4 endpoint table (4 columns), §5 error table (2 columns). Document ends at §5 with no audit footer.

## Numeric completeness gate (self-run against SCAFFOLD.yaml)

- **Endpoints: 72/72** — every `method + path` appears. Misses: none.
- **Errors: 53/53** — every `errors[].id` appears. Misses: none.
- **Domain constants: 75/75** — every key's literal value is rendered in prose at its point of use. Misses: none.

Additional gates run:
- **Contract 1 (field-name coverage): PASS** — 137 `entities[].fields[].name` + 80 distinct `endpoints[].input` identifiers, 0 missing from backticks. All enum member strings (across every `constraints: one of:` list) present, 0 missing. All 7 `roles[].name` present.
- **Contract 2 (rule coverage): PASS** — 39/39 ladder rungs stated in explicit priority order with scope and error id; 3/3 `concurrency_rules` (write endpoint + `expected_<parent>_version` + error id + 412); **69/69 state-machine transitions rendered as explicit `FROM → TO` arrow pairs** across all 14 axes, with preconditions and side effects; 19/19 calculations in reconstruction-grade prose (both pellet ladders, both lab range families, FEFO ranking + `created_at` tie-break, per-line vs per-row rounding, the 6-step invoice order, the 7-step pause-credit order, final-installment residual absorption, `FINAL_RESIDUAL` selector); 3/3 conservation identities with their compensating pairs.
- **Contract 3 (§3 path purity): PASS** — 1208 backtick tokens scanned in §3; 0 starting with `/`, 0 bare HTTP methods, 0 method+path combos.
- **§2.2 byte-for-byte identical** to `section-2.2-response-structure.md`.
- No fuzzy/approximating words present.

## Explicitly un-prejudged friction points

These are places where the scaffold under-specifies or self-disagrees. I stated the rule as far as the scaffold supports it, invented no enforcement, and dropped nothing:

1. **`variant` on the therapy-status read.** Rung 5's exhaustive enum list names "the therapy-status endpoint's `variant`", but that endpoint's `input` declares only `hormone_type`, `consult_id?`, `lab_panel_id?`, `scheduled_start?` — and no member set for a `variant` exists anywhere. I reproduced rung 5's list verbatim in §2.9 but did **not** add a `variant` parameter to the §3.4 narrative, since inventing members would make valid requests rejectable.
2. **`recall_impact_counts` field names.** The calculation names its outputs `projected_*` / `actual_*`, while the endpoint's `output` shape declares unprefixed `released_allocation_count` etc. I used the endpoint's declared response names and let `variant` select which computation fills them.
3. **`pellets_wasted` upper bound has no declared error.** The perform transition's precondition (`pellets_wasted ≤ pellets_opened`) carries no `error_id`. I routed it to `ERR_VALIDATION` as the only available code (rung 4).
4. **`provider_type: PHYSICIAN` requirement has no declared error.** Three fields (`published_by_provider_id`, `Consult.physician_id`, `StandingOrder.physician_id`) require a `PHYSICIAN`-typed provider with no code declared. Routed to `ERR_VALIDATION`.
5. **`hold_kind FINANCIAL` split has no declared error.** The endpoint admits `[ClinicAdmin, Physician]`, but the RBAC matrix makes `hold_kind FINANCIAL` `ClinicAdmin`-exclusive. I stated a `Physician` attempting it gets `ERR_FORBIDDEN_ROLE`.
6. **Rung 14 scope, summary vs detail.** The `Patient.eligibility_status` `CLEAR → CLINICAL_HOLD` side-effect text names only perform and administer, while rung 14's `applies_to` also includes scheduling. I resolved toward the rung's `applies_to` (all three).
7. **Financial-hold-clear procedure release.** The `DUAL_HOLD → CLINICAL_HOLD` leg omits the "procedures return to `SCHEDULED`" side effect that the `FINANCIAL_HOLD → CLEAR` leg and the endpoint both declare. I resolved toward the endpoint's unconditional declaration (any financial clear releases them), and stated `consent_record_id` clearing from the authoritative Procedure-axis transition.

**Orchestrator note:** these 7 friction points are carried forward to Steps 5, 6 and 7 as *explicitly un-prejudged* — each downstream subagent is told the friction exists and must resolve it against PRD prose on its own, without being told the others' resolution.

## Step 5: Generate unit tests — 2026-08-04T06:08:00.000Z

Subagent summary (verbatim):

Test infrastructure and suite are complete and verified.

## Output

- **`test_helpers/`** — 9 modules, 2,589 lines: `types.py` (all entity TypedDicts + 30 enums; `Protocol` correctly omits `updated_at`/`version`), `api_client.py` (**all 72 endpoint methods**), `api_errors.py` (**all 53 error IDs** registered with the framework's status map), `assertions.py` (per-entity assertions, the three conservation checkers, `parse_instant`/`assert_same_instant`/`days_between`/`hours_between`), `factories.py`, `constants.py`, `test_users.py` (per-instance builders for the three `entity_backed` roles), `fixtures.py` (808 lines: 5 tiers — primitives, clinic backdrop, `setup_pellet_procedure(target_status=…)` walking the primary axis, `setup_redose_ready`, `setup_active_financing_plan`, `setup_injection_visit`, `setup_notified_consent_requirement`).
- **`test_suite/`** — conftest + 12 domain-named files, 4,443 lines.

## Coverage

- **109 test functions** (122 pytest items; one parametrized family of 14 covers the per-entity 404 codes).
- **Queue A: 26/26 instances, all with ≥2 tests** (53 tests; the depth-5 recall cascade got 3).
- **Queue B: 56/56 non-stub instances covered**; the 7 `excluded_because` stubs were verified to cross-reference real difficulty instances and were not translated.
- **Skipped instances: none.** Every instance in both queues passed the PRD-first two-condition filter.

Verified mechanically: every PRD citation survives a literal whitespace-normalised grep of `PRD.md` and is ≥8 words; every docstring ends with exactly one `Design:` tag resolving to a real non-stub instance; no `skip`/`skipif`/`xfail`; no `validate_error_is_one_of` (none was needed — every error is uniquely derivable); no raw-string timestamp equality anywhere (all instants compared semantically); no scaffold references in emitted code; pyflakes clean.

## The 7 un-prejudged friction points

| # | Landing | Why |
|---|---|---|
| 1 | **Not asserted** | Rung 5 names a `variant` for the therapy-status read, but §3.4's endpoint prose names only `hormone_type` plus optional `consult_id`/`lab_panel_id`/`scheduled_start`, and no member set is declared. No instance in either queue sends or reads it, so nothing was weakened — both therapy-status tests call the endpoint exactly as §3.4 describes. |
| 2 | **Asserted, unprefixed** | §3.8 names the six fields unprefixed for *both* variants ("the same six response fields are filled from what the cascade really wrote") plus "echoes the `lot_id` and the `variant`". PRD is the contract, so `released_allocation_count`… are asserted verbatim in the PROJECTION (2/1/2/1/2/2) and ACTUAL (1/2/1/1/1/1) reads. |
| 3 | **Not asserted** | §3.5 *does* resolve it — "rejected as a request-shape violation with `ERR_VALIDATION`" — but no queue-A or queue-B instance covers it, and freelance discovery is forbidden. |
| 4 | **Not asserted (rule); adjacent instance asserted)** | §2.1 resolves it to `ERR_VALIDATION`, but no instance covers the licensure-class rule. The nearest instance (`Corner/rbac/nurse_injector_cannot_author_a_standing_order`) is a rung-3 role denial, which pre-empts rung 4, and is asserted as `ERR_FORBIDDEN_ROLE`. |
| 5 | **Not asserted** | §3.1 resolves it to `ERR_FORBIDDEN_ROLE`, but no instance asserts the rejection. The rule is honoured operationally: `set_hold` routes FINANCIAL through `ClinicAdmin` and CLINICAL through the acting `Physician`. |
| 6 | **Fully asserted** | No ambiguity survives in PRD prose: rung 14's endpoint list and §3.1's "scheduling, performing and injection administration are all blocked at rung 14" agree exactly. Asserted on booking and on injection administration. |
| 7 | **Not asserted** | §3.1 states the `SUPPLY_HOLD → SCHEDULED` release at endpoint level ("Clearing the financial hold has a reach…"), unconditional across both legs; the state-machine paragraph adds no per-leg exception. No instance exercises `DUAL_HOLD → CLINICAL_HOLD` with a held procedure. The one dual-hold instance clears the *clinical* hold (`DUAL_HOLD → FINANCIAL_HOLD`) and is fully asserted. |

## One derivation worth recording

**Rung 10 vs rung 11.** Seven instances depend on which fires for a terminal row. I resolved it against PRD alone: rung 10 covers non-terminal states from which the transition isn't declared (re-releasing a `RELEASED` lot, resuming an `ACTIVE` membership, voiding a `SCHEDULED` visit, reinstating an `ACTIVE` order); rung 11 covers the nine enumerated terminal sets. This is the only reading under which rung 11 is reachable at all — no transition is ever declared *out of* a terminal state, so a strict rung-10-first reading would render rung 11 and its exhaustive per-axis terminal list dead. Asserted exactly, including the pair in `test_12` where the same `CANCELLED` procedure yields `ERR_STANDING_ORDER_INVALID` (403) to a nurse and `ERR_ALREADY_TERMINAL` (409) to a physician.

## Step 6: Generate implementation — 2026-08-04T06:04:00.000Z

Subagent summary (verbatim):

Implementation complete and verified.

## Deliverable

`/home/ubuntu/github/CodingPRD/tasks/task_0922_hormone_pellet_wellness_injection/workspace/implementation/`

**31 files, 4,326 Python lines** across 29 modules plus `start.sh` and `requirements.txt`. Layout: `app.py`, `config.py` (75 constants), `errors.py` (53 codes), `store.py`, `util.py`, `envelope.py`, `serializers.py`, `reqctx.py` (rungs 1–5), `access.py` (rungs 6–8), `gates.py` (rungs 9–39), `calc.py` (all 19 calculations), `cascades.py`, and `routes/` (16 modules). Every module was authored in bounded writes and `ast.parse`-verified.

## Endpoint gate

`SCAFFOLD 72 / REGISTERED 72 / MISSING 0 / EXTRA 0` — computed programmatically by parsing `SCAFFOLD.yaml`'s `endpoints[]`, booting the app in-process, dumping `app.url_map`, and diffing with `{param}`↔`<param>` normalisation. **Fresh boot holds 0 entity rows** (asserted in the same gate: `sum(len(t) for t in store.db.values()) == 0`). No seeding anywhere; in-memory dicts only, no disk or SQLite.

## Recurring bugs — adjudicated

**A. Timestamp rendering.** One rule, everywhere: **every** datetime in **every** response body renders as `YYYY-MM-DDTHH:MM:SS.mmmZ` (exactly three fractional digits, trailing `Z`) — server-stamped (`created_at`, `performed_at`, `resulted_at`, `effective_at`, …), computed (`due_at`, `review_due_at`, `expires_at`, `period_end`, schedule `due_date`), *and* echoed input (`drawn_at`, `scheduled_start`, `valid_from`, `expiry_date`, `onset_at`, `first_due_date`), plus `current_utc` on the clock endpoint. Input parses with or without fractional digits and with `Z`/offset/naive. `date_of_birth` is a calendar-date string, not a datetime, and is echoed verbatim. (PRD §2.4.)

**B. Enum error routing.** Rung 5 gives an exhaustive field list plus "No other field routes here", so it is honoured **exactly**: only those field instances raise `ERR_INVALID_ENUM`. Every other enum-membership failure on a *declared input* raises `ERR_VALIDATION` at rung 4 — in practice the single field this touches is `hormone_type` on the therapy-status read. Optional list-endpoint **filters** are not declared inputs and are never enum-validated; an unknown filter value simply matches zero rows.

## The 7 friction points — chosen readings

1. **therapy-status `variant`** — the endpoint's declared inputs (§3.4 narrative + §4 table) are `hormone_type` plus optional `consult_id`/`lab_panel_id`/`scheduled_start`; no `variant` exists and no member set is declared anywhere. Reading taken: rung 5 is a no-op here — a supplied `variant` is an unrecognised query param, ignored, never an error.
2. **`recall_impact_counts` names** — §3.8 states the six response fields unprefixed and says "the same six response fields" are filled under `ACTUAL`. Response is `{lot_id, variant, released_allocation_count, flagged_allocation_count, affected_procedure_count, held_procedure_count, notification_count, surveillance_event_count}`; `projected_`/`actual_` are formula-side names only.
3. **`pellets_wasted <= pellets_opened`** — §3.5 says verbatim "rejected as a request-shape violation with `ERR_VALIDATION`". Routed to `ERR_VALIDATION` (400); the shape half runs at true rung 4, the state-dependent comparison immediately after path resolution so it still pre-empts rungs 7–39 (including the rung-9 gate).
4. **`provider_type: PHYSICIAN` on the three FK positions** — §2.1 says verbatim "rejected as a request-shape violation with `ERR_VALIDATION`". Applied to `published_by_provider_id` (protocol), `physician_id` (consult), `physician_id` (standing order) only, checked immediately after rung-7 resolution (so a *missing* provider still 404s first).
5. **`hold_kind: FINANCIAL` role split** — §3.1 says verbatim "a `Physician` attempting an action with `hold_kind` `FINANCIAL` is rejected with `ERR_FORBIDDEN_ROLE`". Evaluated as an extension of **rung 3**, so it pre-empts rungs 4 and 5.
6. **Rung 14 scope** — §2.9 rung 14 *and* §3.1 ("scheduling, performing and injection administration are all blocked at rung 14") *and* §3.4 all name three endpoints. Applied to `POST /clinic/procedures`, `.../perform` and `.../administer`; the narrower state-machine note was not followed.
7. **`DUAL_HOLD → CLINICAL_HOLD` procedure release** — §3.1, §3.6 and the endpoint's own side-effect list all state the release unconditionally for FINANCIAL+CLEAR. Fires on **every** financial clear, including the DUAL_HOLD leg.

## Other undeclared-error decisions (stated for the record)

Three transition preconditions carry no `error_id`; each routes to rung 10's `ERR_INVALID_STATE` (409): open-supply's "plan is complete", reinstate's "every referencing adverse event is CLOSED", activate's "procedure not CANCELLED/VOIDED". Uniqueness violations (`email`, `npi`, `lot_code`) route to `ERR_VALIDATION`. Rung 11 is evaluated **before** rung 10 in code (terminal state → `ERR_ALREADY_TERMINAL`, otherwise undeclared origin → `ERR_INVALID_STATE`) because the strict ladder order would make `ERR_ALREADY_TERMINAL` unreachable. Per §2.5, `version` increments **once per row per request** even when a cascade touches a row on two hops.

## Verification

Six smoke suites (~230 assertions) all pass from fresh boots, zero server tracebacks. Confirmed worked examples: pellet ladder (T1150→7/1200, E80→4/85, E100→4/100); per-line rounding (E 3×25+1×10 → 14982); facility-fee waiver on the nose (42625) and the PLUS member paying *more* (45862); pause credit 15257 (not 15249); financing `[7773×5, 7775]`; series `[3287×7, 3291]` and refund 26296; breakage split (row keeps id/rank, sibling WASTED row minted); all three conservation identities after every mutation; FEFO expiry+`created_at` tie-break; allocation atomicity (short walk mutates nothing); allocate→cancel round trip restoring all five buckets exactly; five-hop CLASS_I recall; four-hop severe-AE cascade freezing another patient's procedures; protocol de-consent cascade; delinquency default cascade and financial-hold clear; mutate-then-reject series expiry; all five re-dose rungs in order; provider-buffer and room boundary geometry; three-person escalated-event closure; all three OCC guards. Cold boot ≈1.5 s.

**Isolation preserved**: no test suite, helper, conftest, or sibling task directory was read.

**Orchestrator isolation note:** Steps 5 and 6 launched concurrently in a single message. **Step 6 finished first** (~2,104 s vs ~2,354 s), so Step 5 was still writing `test_suite/` after impl-gen exited — but Step 5 wrote incrementally throughout, so test files were on disk during impl-gen's later stretch. Containment: (a) Step 6's prompt forbade reading/globbing/grepping for `test_suite`, `test_helpers`, `conftest`; (b) it confirmed no such read; (c) an orchestrator grep of the whole impl tree for `test_suite|test_helpers|conftest|pytest` returned **empty**. Step 7 is briefed on the overlap and told to STEP-1 audit *passing* tests in the categories a breach would show up in.

**Orchestrator pre-flight checks:** impl persistence grep (`sqlite|pickle|json.dump|shelve|/tmp/|open(`) **empty**; `def test_` = 109 == `Design:` tags = 109; `skip|xfail|skipif` = **0**; impl 4,326 lines / 31 files. Co-tenant pipeline (task_0923) mid-sweep at 2 concurrent runners → `workspace/sweep.sh` pre-staged as **4 waves of 2**.

## Step 7: Run tests and iterate — 2026-08-04T06:20:00.000Z

Subagent summary (verbatim):

Sweep came back clean on the first iteration. Full report:

## Summary

**Iterations run:** 1 (no fixes were needed, so no re-run was required).

**Final sweep — per-round pass/total** (8 rounds, 4 waves of 2, `--isolation per-test-server`):

| Round | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 |
|---|---|---|---|---|---|---|---|---|
| passed/total | 122/122 | 122/122 | 122/122 | 122/122 | 122/122 | 122/122 | 122/122 | 122/122 |

All rounds `failed=0 errors=0 skipped=0`, `rc=0`. Wall time ~72 s/round.

**Tests deleted:** none.
**Fixes applied to `test_suite/`:** none.
**Fixes applied to `test_helpers/`:** none.
**Fixes applied to `implementation/`:** none.

### Isolation-overlap audit (a)–(e)

- **(a) Raw-string timestamp equality — zero found.** `grep -rnE '==\s*"20[0-9]{2}-..T'` over `test_suite/` + `test_helpers/` is empty. All 28 instant comparisons route through `assert_same_instant` (`test_helpers/assertions.py:33`), which parses both sides and compares instants. The only literal-looking timestamp assertions are `is None` null checks. No `startswith`/`endswith`/`.000Z` shape hacks.
- **(b) Unpinned list ordering — zero found.** Every index into a server list response is guarded by a preceding `assert len(...) == 1` (`test_11:208/215/258`, `test_03:110`). The one list-equality assertion (`test_01:263`) is over a filter that PRD-provably yields a single row, and PRD §2.3 pins ordering verbatim ("List results are ordered by `created_at` ascending unless a specific narrative below says otherwise"). Indices like `administered[3]`/`patients[0]` are into locally built Python lists, not server order.
- **(c) Computed-field silence — zero found.** Mechanical check: of 148 distinct `["field"]` tokens asserted in `test_suite/`, 14 do not appear in PRD.md — and all 14 are local fixture-dict keys (`front_desk_headers`, `plan_id`, `trough_panel`, `large_lot`, …), not response fields. Every response field asserted is named in PRD prose as a persisted/response attribute (spot-checked `series_debit_cents` §3.7, `per_visit_value_cents` §3.7, `lab_reference_band` §3.3, `planned_small/large_count` §3.3). The therapy-status projection's fields (`f1..f5_ok`, `redose_eligible`, `anchor_performed_at`, both rolling variants) are enumerated verbatim in PRD line 258.
- **(d) Optional-input defaults — zero found.** Every optional input a test pins has its default stated verbatim: `is_trough_draw` "defaults to false" (line 228), `active` "defaults to true" (line 336), `clinical_hold`/`financial_hold` "both start false" (line 200). The `reason`/`note`/optional-FK fields have no default asserted anywhere.
- **(e) Exact key-set projections — zero found (one PRD-covered absence assertion).** No `set(data.keys()) == …` anywhere. The only absence assertions are `test_01:183-184` (`"updated_at" not in data`, `"version" not in data` on Protocol), covered verbatim twice: line 100 "The `Protocol` record is immutable once published: it carries only `id` and `created_at`, and neither `updated_at` nor `version` appears on it at all."

Additional breach check: no test file imports or references any implementation module (`grep` for `from app|store|calc|gates|cascades import` over both test dirs is empty; the two "implementation" hits are prose inside a docstring and a comment). Also verified all 53 `ERR_*` ids referenced by tests appear in PRD.md.

### Zero-fix verification checklist

1. All 8 `results.N.json` exist and parse; **122 individual test rows per round** (not just counters), rounds 1–8.
2. **Sorted test-name set identical across all 8 rounds** — SHA-1 of the joined sorted name list is `a2de24b02c5d…` for every round.
3. Collected count arithmetic confirmed: `grep -rh "def test_" test_suite/ | wc -l` = **109**; exactly one `@pytest.mark.parametrize` family (`NOT_FOUND_LOOKUPS`, **14 entries**, `test_01_registration_and_records.py:64`); 109 − 1 + 14 = **122** = runner's collected count.
4. **Zero** `pytest.mark.skip` / `xfail` / `skipif` in `test_suite/` or `test_helpers/` (grep exit 1). The word "skip" appears only in PRD-quoting docstrings and one test name.
5. `grep -rE "sqlite|pickle|json.dump|shelve|/tmp/|open\(" implementation/ --include=*.py` is **empty** (exit 1). `store.py` is a dict-of-dicts with an explicit "Nothing here is seeded" contract; the logical clock defaults to `2026-05-01T00:00:00Z` on every boot.
6. **No implementation or test file modified after `results.8.json`** (`find … -newer` empty), so the green result stands for the shipped code.

Supplementary integrity checks: implementation is **4,326 LOC across 29 `.py` files**, and its **72 `@app.route` registrations exactly match the 72 endpoint rows** in PRD §4's table. Per-test-server isolation is provably live: `test_helpers/fixtures.py:55` defaults `new_patient` to `p1@example.com`, reused across 7 tests, while PRD line 200 requires email "unique across all patients" — if state leaked between tests, those would fail with a duplicate-email error.

### Friction points (adjudicated against PRD, all inert or PRD-resolved)

1. therapy-status `variant` — no test sends it; PRD line 258 lists no member set. Inert.
2. `recall_impact_counts` naming — PRD line 352 names the six **unprefixed** fields (`released_allocation_count`, …); tests assert exactly those. Resolved.
3. `pellets_wasted <= pellets_opened` — PRD line 278 routes it verbatim to `ERR_VALIDATION`. Resolved.
4. `provider_type: PHYSICIAN` FK check — no test reaches it; the one adjacent test (`test_12:165`) asserts `ERR_FORBIDDEN_ROLE` at rung 3, which pre-empts. Inert.
5. `hold_kind: FINANCIAL` role split — PRD line 204 states `ERR_FORBIDDEN_ROLE` verbatim. Resolved.
6. Rung 14 `applies_to` — PRD line 149 enumerates the three endpoints verbatim. Resolved.
7. `DUAL_HOLD → CLINICAL_HOLD` procedure release — PRD lines 206 and 294 state the release unconditionally on financial clear; no test asserts an uncovered variant. Resolved.

Both independently-arrived ladder-order readings (rung 11 before rung 10; rung-5 exhaustive enum list with everything else to `ERR_VALIDATION`) are backed by PRD line 140's closing sentence "No other field routes here" and produced zero failures across 976 test executions.

**Orchestrator independent re-verification of the zero-fix claim** (a clean first sweep is indistinguishable from a false-clean without this):
- Re-parsed all 8 `results.N.json` myself: `passed=122 total=122`, **122 individual rows each**, status distribution `{'passed': 122}` in every round.
- SHA-1 of each round's sorted test-name list = `a2de24b02c5d` — **byte-identical across all 8 rounds** (no round silently collected a smaller suite).
- `find test_suite test_helpers workspace/implementation -name '*.py' -newer results.8.json` → **empty**; the 122/122 × 8 result stands for the shipped code.
- Independent `app.url_map` diff against `SCAFFOLD.yaml` `endpoints[]` (with `{param}`↔`<param>` normalisation): **72 scaffold / 72 registered / 0 MISSING / 0 EXTRA**, and `sum(len(t) for t in store.db.values()) == 0` at fresh boot.

## Step 8: Finalize PRD — SKIPPED — 2026-08-04T06:22:00.000Z

Step 7 exited on the first 8-round sweep with **0 deletions, 0 `test_suite/` fixes, 0 `test_helpers/` fixes, and 0 `implementation/` fixes**. There is no `<step_7_diff>` to patch against — `PRD.md` already determined every behavior the implementation exhibits at every site the suite exercised. Per the skip condition, no subagent was spawned and `PRD_FINALIZED.md` is deliberately absent. Step 9 therefore starts from `PRD.md` and carries the entire completeness burden.

## Step 9: Complete PRD — 2026-08-04T06:37:00.000Z

Subagent summary (verbatim):

Structure intact — 511 lines, all tables preserved, every change in-paragraph.

## Summary

**Source:** `PRD.md` — 511 lines, 127,254 chars
**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_0922_hormone_pellet_wellness_injection/workspace/PRD_COMPLETED.md` — 511 lines, 143,038 chars (**+15,784 chars**, 49 lines revised, 0 lines added/removed, 0 new sections)

**Counts:** 49 edits — **38 ambiguity-pins**, **11 mismatch-revisions**.

### Changes

- **§2.1 (Physician identity)** — revise — mismatch — PRD claimed provider ownership compares the row's provider FK to `X-User-ID`; impl only checks that `X-User-ID` resolves to a `Provider` row (`access.py:70-77`).
- **§2.1 (Patient identity)** — insert — mismatch — patient ownership is not applied to collection list endpoints; a Patient lists everyone's rows (`access.py:80-92`, every `list_*` handler calls `ownership(ctx)` with no `patient_id`).
- **§2.1 (licensure class)** — revise — ambiguity — `ERR_VALIDATION` is raised after rung 7 and before rung 8, and only on `physician_id`/`published_by_provider_id` (`access.py:27,56-67`).
- **§2.2 (`api_request_timestamp`)** — revise — ambiguity — read from the logical clock (`envelope.py:8-12`).
- **§2.2 (pagination meta)** — revise — ambiguity — the 201 allocation array carries no pagination keys (`envelope.py:20-25`, `procedures.py:247`).
- **§2.3 (ordering)** — insert — ambiguity — `created_at` ties broken by server write order; allocation listings are in creation order, not rank order (`reqctx.py:249-250`, `store.py:99-101`).
- **§2.3 (filters)** — insert — ambiguity — raw-string comparison, off-enum value yields an empty page not a 400, nulls unmatchable, undeclared query params ignored (`reqctx.py:231-246`).
- **§2.5 (version)** — insert — ambiguity — once per row per request even when a cascade touches it twice (`store.py:80-90`).
- **§2.7 (allocation OCC)** — revise — ambiguity — rung 11 still applies before the version check (`procedures.py:205-207`).
- **§2.9 rung 4** — insert — ambiguity — absent/non-object body treated as `{}` (`reqctx.py:210-222`).
- **§2.9 rung 5** — revise — mismatch — removed the phantom "`variant` on the therapy-status read"; pinned that therapy-status `hormone_type` routes to `ERR_VALIDATION` (`patients.py:70`, `reqctx.py:146-152`).
- **§2.9 rung 7** — revise — mismatch — `ordered_by_provider_id` was missing from the fixed FK order (`access.py:8-24`).
- **§2.9 rung 8** — revise — mismatch — list endpoints unscoped; provider id not compared to the row (`access.py:70-92`).
- **§2.9 rung 10** — insert — mismatch — rung 11 is evaluated **before** rung 10 (`gates.py:12-19`).
- **§2.9 rung 11** — insert — ambiguity — axes absent from the terminal set (lab panel, consent, allocation, recall axis) always answer `ERR_INVALID_STATE` (`config.py:144-154`).
- **§3.1 (registration)** — revise — ambiguity — `date_of_birth` is an unvalidated opaque string; duplicate `email` → `ERR_VALIDATION` (`patients.py:26,33-35`).
- **§3.1 (hold role split)** — insert — ambiguity — extends rung 3, reads the raw body value before rungs 4/5/6 (`patients.py:14-17`, `reqctx.py:193-201`).
- **§3.1 (financial clear)** — insert — ambiguity — the procedure release fires on the `DUAL_HOLD → CLINICAL_HOLD` leg too, and a no-op clear still bumps `version` (`patients.py:128-136`).
- **§3.1 (providers)** — revise — mismatch — `active` governs nothing; no endpoint reads it. Duplicate `npi` → `ERR_VALIDATION` (`providers.py:24-32`).
- **§3.2 (protocol cascade)** — insert — ambiguity — hops 3–4 skipped when hop 2 supersedes nothing (`cascades.py:132-133`).
- **§3.2 (consent signing)** — insert — ambiguity — `protocol_version` is never validated at signing (`consents.py:39-46`).
- **§3.3 (acknowledge-critical)** — insert — ambiguity — non-`CRITICAL_FLAGGED` origin → `ERR_INVALID_STATE`, never `ERR_ALREADY_TERMINAL` (`lab_panels.py:104`).
- **§3.3 (safety ceiling)** — insert — ambiguity — "most recent" = by `created_at`/write order, not `drawn_at` (`gates.py:95-104`).
- **§3.4 (booking refs)** — insert — mismatch — consult/panel/membership are never checked against the patient, and `provider_id` is never class- or `active`-checked (`procedures.py:71-77`).
- **§3.4 (re-dose)** — insert — ambiguity — anchor present + no `lab_panel_id` → `ERR_LAB_STALE` (`procedures.py:40-44`, `calc.py:172`).
- **§3.5 (lot receipt)** — insert — ambiguity — duplicate `lot_code` → `ERR_VALIDATION`, tested before rung 29 (`pellet_lots.py:35-43`).
- **§3.5 (FEFO ties)** — insert — ambiguity — third tie-break is receipt order (`calc.py:106`).
- **§3.5 (allocation response)** — insert — ambiguity — 201 array of only the newly created rows (`procedures.py:247`).
- **§3.5 (re-plan)** — revise — mismatch — supersession and new plan commit atomically; a short walk leaves the old set intact (`procedures.py:218-229`).
- **§3.5 (allocation legs)** — revise — mismatch — `OPENED → RELEASED` also fires from a superseding re-plan, not only from a cascade (`procedures.py:210-213`).
- **§3.5 (open-supply)** — insert — ambiguity — incomplete plan → `ERR_INVALID_STATE`, after the state gate, before rung 16 (`procedures.py:276-280`).
- **§3.5 (perform)** — insert — ambiguity — `pellets_wasted > pellets_opened` fires after rung 6 and before rungs 8/9/10/11/12 (`procedures.py:303-308`).
- **§3.6 (cancel roles)** — insert — ambiguity — the `SUPPLY_OPENED`/`SUPPLY_HOLD` role narrowing sits after rung 6, before rung 8 and the state gate (`procedures.py:369-372`).
- **§3.6 (refund quote)** — insert — ambiguity — no state gate; earliest plan wins when several name the procedure (`procedures.py:442-450`, `calc.py:257-259`).
- **§3.6 (void)** — insert — ambiguity — `performed_at`, `charge_cents`, pellet counters all retained (`procedures.py:416-435`).
- **§3.6/§3.9 (DRAFT plan)** — revise — mismatch — a DRAFT plan's `refunded_cents` also subtracts the wasted-pellet charge (`cascades.py:367-371`).
- **§3.7 (visit void)** — revise — mismatch — pack returns to `ACTIVE` whenever it reads `EXHAUSTED` (not only when this visit emptied it); `payment_source`/`series_debit_cents` retained (`injection_visits.py:173-190`).
- **§3.7 (tier change)** — insert — ambiguity — declared from `ACTIVE` and `PAUSED`; pause fields untouched (`memberships.py:127-132`).
- **§3.7 (pack expiry)** — insert — ambiguity — forfeiture writes only for a pack still `ACTIVE` (`gates.py:179-191`).
- **§3.8 (reinstate)** — revise — ambiguity — non-`CLOSED` events → `ERR_INVALID_STATE` (`standing_orders.py:108-113`).
- **§3.8 (severe cascade)** — insert — ambiguity — hops 2–4 skipped when no order named or order not `ACTIVE` (`cascades.py:162`).
- **§3.8 (recall hop 3)** — insert — ambiguity — 3a skips procedures whose `recall_status` isn't `NONE`; 3b's non-freeze branch recomputes `pellets_allocated` and bumps `version` only on change (`cascades.py:216-232`).
- **§3.8 (recall hop 5)** — insert — ambiguity — surveillance event's `onset_at`/`review_due_at`/FK nulls (`cascades.py:250-265`).
- **§3.8 (recall impact)** — insert — ambiguity — `assume_severity` enum-checked then ignored under `ACTUAL` (`calc.py:367-412`).
- **§3.8 (notifications)** — insert — ambiguity — the five list filters, 7-day `due_at` for every type (`notifications.py:30-35`, `cascades.py:68`).
- **§3.9 (activate)** — revise — ambiguity — terminal procedure → `ERR_INVALID_STATE` (`financing.py:102-106`).
- **§3.9 (payments)** — insert — ambiguity — `DELINQUENT → ACTIVE → PAID_OFF` chains in one request (`financing.py:133-136`).
- **§3.9 (sweep)** — revise — mismatch — `DEFAULTED` is reachable directly from `ACTIVE`; only genuinely changed plans bump `version` (`cascades.py:324-344`).
- **§3.9 (counters)** — revise — ambiguity — semantics of all seven counters, notably `patients_held` counting only newly-held patients (`cascades.py:296-352`).

### Came back clean (checked exhaustively, PRD already pinned uniquely)

- **Timestamp rendering** — `util.fmt_dt` emits exactly three fractional digits + `Z` for every instant, server-stamped and caller-echoed alike; `parse_dt` normalises offsets to UTC. §2.4 already states this literally, character for character. (The usual highest-value catch is absent here.)
- **All 16 serializer projections** — every key each entity emits, and every omission (`Protocol` carrying neither `updated_at` nor `version`; `schedule[]` emitting exactly `index`/`due_date`/`amount_cents`/`status`) matches §2.5 and the §3 narratives.
- **Rung 14's endpoint scope** — exactly `POST /procedures`, `/perform`, `/administer`; PRD's list is exhaustive and correct. Same for rung 39 (book + perform only).
- **`recall_impact_counts` field names** — the same six keys under both variants, plus `lot_id` and `variant`; every PROJECTION and ACTUAL definition matches §3.8 term for term.
- **All 19 calculations** — pellet ladder, both band rulers, both rolling-exposure variants, FEFO walk, per-line pellet rounding, discount-then-facility-fee ordering, cancel-fee ladder, both refund variants, financing schedule residual, pause credit, pack pricing and final-residual redemption, payment-source waterfall, eligibility projection. Every rounding step and boundary matches §2.6 and §3.
- **Rung 7's FK resolution order** (other than the missing `ordered_by_provider_id`) and the 404-before-403 discipline throughout.
- **The three conservation identities** — all five lot buckets, the four entitlement buckets, and both financing legs balance after every mutation path, including the wastage split.
- **Error catalogue §5** — all 53 codes present in `errors.py` with matching HTTP statuses; no orphans in either direction.
- **Endpoint table §4** — all 72 routes and every authorized-role list match the `@endpoint(roles=...)` declarations exactly.

**Orchestrator final verification:** `workspace/PRD_COMPLETED.md` present at 511 lines / 143,038 chars (same line count as `PRD.md`, +15,784 chars — all edits in-paragraph, 0 new sections); `PRD_FINALIZED.md` correctly absent (Step 8 skipped); 8 `results.N.json` present; **no `.py` under `test_suite/`, `test_helpers/` or `implementation/` modified after `results.8.json`** — Step 9 touched only `PRD_COMPLETED.md`, so the 122/122 × 8 sweep still stands for the shipped code.

---

# PIPELINE COMPLETE — task_0922_hormone_pellet_wellness_injection

**122/122 tests passing on all 8 stability rounds, zero Step-7 deletions and zero fixes of any kind.**

| | |
|---|---|
| Difficulty | beyond-Expert |
| Entities | 16 |
| Endpoints | 72 |
| State-machine axes | 14 (13 non-linear) |
| Calculations | 19 (7 with variant forks) |
| Error codes | 53 |
| Validation ladder | 39 rungs (rung 9 = global standing-order write gate) |
| OCC rules | 3 |
| Conservation invariants | 3 |
| Declared constants | 75 |
| Cascade depth | 5 (lot recall) |
| PRD | 511 lines / ~18.1k words |
| Implementation | 4,326 lines / 31 files |
| Tests | 109 functions / 122 pytest items |
| Step 7 | 1 iteration, 0 deletions, 0 fixes |
| Step 8 | skipped (zero-fix) |
| Step 9 | 49 edits (38 pins + 11 mismatches) |
