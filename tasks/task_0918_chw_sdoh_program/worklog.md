# Worklog — task_0918_chw_sdoh_program

Scenario (verbatim from user):
> 918. Community Health Worker & SDOH Program (provider side): patient roster & risk/SDOH screening, closed-loop referral (food/housing/transport), home-visit & goal, resource inventory & eligibility, encounter & time tracking, payer/grant billing, outcome & escalation, reporting

Difficulty target: **beyond-Expert** (user asked "generate task hard than expert level").

## Step 1: Create task directory — 2026-08-03T17:27:00.000Z

Created `tasks/task_0918_chw_sdoh_program/` and `tasks/task_0918_chw_sdoh_program/workspace/`. Index 0918 = highest existing (0917) + 1.

## Step 2: Generate scaffold — 2026-08-03T18:30:00.000Z

All three artifacts are written and verified clean.

## Output

- `SCAFFOLD.yaml`, `SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`

## Reported numbers

| Dimension | Value | Target |
|---|---|---|
| Entities | 15 | 14–16 |
| Endpoints | 70 | 55–70 |
| State machines | 11 (**11 non-linear**) | 9–11, ≥5 non-linear |
| Calculations | 9 (**6 dual-variant**) | 5+ dual-variant |
| Error codes | 33 | 28–34 |
| Validations / ladder rungs | 43 / **17** | 28+ / 14+ |
| OCC rules | 3 (ResourceOffering, GrantAward, Patient) | 2–3 |
| Conservation invariants | 4 | 2+ |
| Max cascade depth | **5** | ≥5 |
| Declared constants | 51, **zero undeclared** | all valued |
| §1.8 instances | 25 across 9 rules (min 3 per rule met, ≥2 required) | ≥18 |
| §1.9 instances | 64 (51 full recipes + 13 `excluded_because` stubs) | — |

**YAML lint:** all three files `yaml.safe_load()` cleanly; no tabs. `scaffold_lint.py` → `VERDICT: clean lint` (672 calls scanned, 0 violations, 24 FKs all reverse-reachable).

## Design spine

Write-gate rung 4 (`Patient.gate_status == RECORDS_HOLD`) sits **above** payload validation, with an exhaustive gated/exempt operation list and a pinned subject-resolution order. Opposite interval conventions coexist: home-visit slots are HALF-OPEN (touching is legal), grant-award periods are CLOSED (touching collides). The depth-5 cascade runs records-hold → referral LAPSED → offering hold released → `availability_state` EXHAUSTED→AVAILABLE → RESOURCE_EXHAUSTED escalation auto-resolved.

## Reachability defects I found and fixed

1. **`MINUTE_ROUNDING_INCREMENT = 5` made round-half-up untestable** — with integer minutes a tie needs `raw ≡ 2.5 (mod 5)`, which is unreachable. Retuned to **6** (standard 0.1-hour billing), so `raw ≡ 3 (mod 6)` produces real ties (21→24, 27→30) and the mode-(b) order fork diverges 72 vs 66.
2. **`GRANT_RATE_TIER_BREAK_CENTS = 500000` was unreachable** — the 480-minute encounter cap meant ~14 charge lines to cross it, so tier 2 (3800) could never be exercised in a test. Retuned to **50000**; tier 2 now engages on the third line.
3. **Rung 4 masked rung 5/6 on dangling `patient_id`** — added the explicit rule that an unresolvable gate subject *skips* rung 4, keeping `ERR_VALIDATION` and `ERR_PATIENT_NOT_FOUND` reachable (corner instance `write_gate_skipped_when_body_patient_id_does_not_resolve` pins it).
4. **Two enum-closure dead ends** — `CommunityHealthWorker.employment_status` declared `INACTIVE` with no producing path (removed from the constraint); `Referral.lapse_reason` omitted `HOLD_EXPIRED`, which the hold-expiry sweep actually writes (added).

Every one of the 33 error codes is referenced by a §1.4/§1.2.1 rule **and** exercised by at least one §1.8/§1.9 recipe; every state in all 11 machines is reachable from its initial state; zero unbound `${var}` placeholders across both design files.

**Orchestrator independent verification:** all 3 files `yaml.safe_load` OK; `endpoints[]` == 70; `entities[]` == 15; ALL_CAPS sweep → 49 residual tokens, every one confirmed an enum member, a calc-variant name, or valued in the nested constants block (`EVAL_RANK_* = 1..5`, `PROGRESS_PCT_MIN/MAX = 0.0/100.0`). Zero undeclared constants.

## Step 3: Copy INSTRUCTION.md — 2026-08-03T18:31:00.000Z

Copied `./INSTRUCTION.md` → `workspace/INSTRUCTION.md`. Pre-staged `workspace/sweep.sh` (8 rounds as 2 waves of 4, marker-file completion).

## Step 4: Generate PRD — 2026-08-03T18:45:00.000Z

PRD generated at `workspace/PRD.md`.

## Structure
487 lines / ~14,700 words. §1 Introduction (3 paras) → §2 with 11 domain-derived subsections → §3 with 10 workflow subsections → §4 (70-row endpoint table, 4 columns) → §5 (33-row error table, 2 columns). Ends at §5 with no audit footer. Written in 8 bounded Write/Edit calls.

## Hard Contract reports

```
Field coverage check:
- entities[].fields:        141 required, 141 present, 0 missing
- endpoints[].input/body:    95 required,  95 present, 0 missing
- endpoints[].output ids:    19 required,  19 present, 0 missing
Status: PASS
```
```
Rule coverage check:
- validations[] with priority:      43 checked, 43 expressed with ladder position, 0 missing
- concurrency_rules[] OCC:           3 checked,  3 expressed, 0 missing
- state_machines[].transitions:     60 checked, 60 fully expressed, 0 missing
- calculations[]:                    9 checked,  9 fully expressed incl. all 6 dual-variant forks, 0 missing
- endpoints[].side_effects:         70 checked, 70 expressed, 0 missing
- entities[].fields[] structured:  141 checked, 141 reconstructible, 0 missing
- sibling-branch symmetry:          11 groups checked, 11 with equal density, 0 asymmetric
- global_constants:                 47 checked, 47 stated with their declared value, 0 missing
- errors[]:                         33 checked, 33 named in §2/§3 prose with HTTP status, 0 missing
- conservation_invariants:           4 checked,  4 stated (§2.10), 0 missing
Status: PASS
```
```
Path purity check (§3 only): 1171 backtick tokens scanned, 0 leaked paths/methods. Status: PASS
```

## Key items worth flagging

- **Write gate (rung 4)** got its own §2.6: exact ladder position stated twice (above payload validation → a malformed request against a held patient returns `ERR_PATIENT_RECORDS_HOLD`, not `ERR_VALIDATION`), the 5-step subject-resolution order including the *unresolvable-subject-SKIPS-the-gate* rule, all **19** gated operations enumerated, and the full exempt list. Count machine-checked (19 = 19).
- **Summary/detail agreement**: caught and fixed one mismatch of exactly the kind noted — prose said "the four payer-side operations" while listing three. Now "three".
- **Both interval conventions stated explicitly** in §2.8 and again at point of use: visit slots HALF-OPEN (touching accepted, no buffer), grant periods CLOSED (touching dates collide).
- **Three resolutions made and stated concretely** (not silences):
  1. `POST /chw/grant-charge-lines` against a `CLOSED` award → `ERR_INVALID_STATE` at rung 9. Encounter split pinned: `DRAFT`/`VOIDED` → `ERR_INVALID_STATE` (rung 8), `LOCKED` → `ERR_MINUTES_ALREADY_FUNDED` (rung 15). Partition is clean so rung order is not observable.
  2. Sweep response `units_returned` = total offering units returned to `available_units` by that run.
  3. `reason` on encounter-void accepted but not persisted; `reversal_reason` on charge-line reverse defaults to `MANUAL_REVERSAL` when omitted.
- **Reroute** strengthened to restate all six shared preconditions with their rungs plus the two reroute-specific ones.
- No scaffold item found named-but-valueless. All 47 global constants carry concrete values and appear in prose with those values.

## Step 5: Generate unit tests — 2026-08-03T19:20:00.000Z

Test infrastructure and suite are complete.

## Output

**`test_helpers/`** (9 modules, 1,977 lines) — `types.py`, `api_client.py` (all 70 endpoints), `api_errors.py` (33 error IDs + status map registered), `assertions.py`, `factories.py`, `constants.py`, `test_users.py`, `fixtures.py`, `__init__.py`

**`test_suite/`** (conftest + 14 files, 5,121 lines):
| File | tests |
|---|---|
| test_01_roster_and_access_control.py | 12 |
| test_02_records_hold_write_gate.py | 6 |
| test_03_screening_and_risk.py | 9 |
| test_04_resource_network_and_eligibility.py | 9 |
| test_05_referral_loop.py | 9 |
| test_06_reroute_chain.py | 4 |
| test_07_sweeps_and_escalations.py | 4 |
| test_08_home_visit_scheduling.py | 6 |
| test_09_home_visit_documentation.py | 8 |
| test_10_care_plan_goals.py | 3 |
| test_11_encounters_and_time.py | 8 |
| test_12_payer_claim_rollup.py | 8 |
| test_13_appeals_and_reporting.py | 4 |
| test_14_grant_funding.py | 11 |

## Counts

- **`def test_` = 101**, **`Design:` tags = 101** — equal; every tag machine-verified to resolve to a real instance name *and* the correct rule_id/section.
- **Queue A: 25 / 25** difficulty instances covered, all with ≥2 tests (0 shortfalls).
- **Queue B: 51 / 51** non-stub corner instances covered, all with ≥1 test (0 shortfalls). 13 `excluded_because:` stubs correctly not translated.
- **101 tests collect cleanly** under pytest; `py_compile` and `pyflakes` clean.

## Skips

**Zero instances were skipped** — all 25 queue-A and all 51 non-stub queue-B instances passed the PRD-first two-condition filter. All ~150 quoted citations `grep -F`-verified against `PRD.md` (each exactly 1 hit).

## Findings worth relaying

1. **Corner-design defect (broken stub pointer).** `Corner/cross_cutting_complexity_layers/offering_version_advances_on_every_inventory_movement` has `difficulty_instance: stale_offering_version_on_referral_create_rejected`, but that name is a **corner** instance (`validations` section), not a difficulty instance. Per the skill's rule, no test was emitted. The claim is covered anyway via the corner instance it points at.
2. **Rung-4 audit passed.** `place_records_hold` called in exactly 4 tests, all in `test_02`, always as the **last** setup step before the trigger. No fixture applies a hold incidentally.
3. **Both interval conventions kept separate.** Half-open visit slots (`test_08`: touching at 10:00:00 accepted, 09:59 rejected) vs closed grant periods (`test_14`: `period_start` == existing `period_end` rejected, day-after accepted).
4. **Timestamps semantic everywhere.** `parse_instant()`/`assert_same_instant()` in `test_helpers/assertions.py`; 44 timestamp comparisons all route through them. Zero raw `==` on `_at`/`_timestamp`. Only string equalities on date-ish fields are `service_month` (`YYYY-MM` bucket label).
5. **Zero pytest skip markers.**
6. **Identity threading enforced.** `make_chw_headers(worker_id)` / `make_partner_headers(org_id)` for every ownership-gated call; distinct owners always get distinct `X-User-ID`s.

## Step 6: Generate implementation — 2026-08-03T19:20:00.000Z

All checks green. Python + Flask, in-memory only, 3,583 lines across 21 files, authored incrementally.

Modules: `ladder.py` 164 (single ordered 17-rung engine; rungs 1–4 built in, 5–17 supplied per endpoint, executed in rung order), `errors.py` 107, `clockutil.py` 120, `store.py` 136, `validate.py` 241, `calc.py` 220, `cascades.py` 150, `serial.py`/`envelope.py` 90/49, `routes_config.py` 296, `routes_screening.py` 160, `routes_resources.py` 207, `routes_referrals.py` 276, `routes_visits.py` 272, `routes_goals.py` 159, `routes_encounters.py` 172, `routes_billing.py` 436, `routes_ops.py` 252, `app.py` 65, `start.sh`/`requirements.txt` 10/1.

## Completeness gate

**scaffold 70 · registered 70 · MISSING 0 · EXTRA 0** (path params normalized before diffing; `/static` excluded).

## Adjudications

**C1 — Timestamps.** Adopted the known-good rule verbatim. `created_at`/`updated_at`/`api_request_timestamp` always `.mmmZ`; every other server-written stamp (`sent_at`, `anchor_screened_at`, `completed_at`, `attested_at`, `denied_at`, `tier_entered_at`, `exhausted_since`, `reversed_at`, `closed_at`, `delivered_at`, `submitted_at`) reproduces the operator's clock string verbatim; arithmetic-derived stamps (`ack_deadline_at`, `hold_expires_at`, `review_due_at`) inherit their source's digit style; caller-supplied instants echoed verbatim. Verified: clock `2026-05-01T00:00:00Z` → `sent_at` `2026-05-01T00:00:00Z`, `ack_deadline_at` `2026-05-04T00:00:00Z`, `created_at` `2026-05-01T00:00:00.000Z`.

**C2 — Enum routing.** No dedicated invalid-enum code in this 33-code catalogue; `ERR_VALIDATION` explicitly covers "undeclared enum member". Every enum-membership failure routes to `ERR_VALIDATION`/400 through one shared helper `validate.enum_value()` — all 15 enum-bearing fields, not just PRD-named ones, plus `allowable_cost_categories` members.

## Prohibitions confirmed

Persistence grep → no matches. No `seed_*`, no module-load entity population. `start.sh` reads `$PORT` (default 10000), binds `0.0.0.0`, `exec`s foreground, guards pip install. Live boot verified: POST `/chw/workers` → 201, GET `/chw/patients/{id}` → 200, no headers → 401.

Also verified live: rung-4 gate pre-empts payload validation and OCC but not rung 2/3; unresolvable gate subjects skip the gate; exactly **19** gated endpoints; half-open visit slots vs closed grant periods; round-per-encounter-then-sum (21→24, 27→30, 30+48=78) vs monthly-aggregated mileage (670+670 per-encounter, 1220 aggregated); all four conservation invariants; the depth-5 records-hold cascade.

## Judgement calls the PRD left open (feed to Step 9)

1. Intra-rung-9 order on referral create/reroute — followed scaffold priorities: **suspended-org (20) before not-enrolled (21)**.
2. `evaluated_count` on eligibility-check = **total** criteria in the ordered list, not the number walked.
3. Version-bump granularity — a row bumps at most **once per request**; a row **created** by the request stays at version 1 even when a later link writes to it.
4. Records-hold lapses increment `unfulfilled_referral_count`.
5. Goal progress has no state precondition — allowed from any status.
6. `AMEND` overwrites `visit_note` only when the key is present in the body.
7. Grant-line rung 8 rejects only DRAFT/VOIDED encounters; LOCKED falls through to rung 15's `ERR_MINUTES_ALREADY_FUNDED`.
8. `api_request_timestamp` reads the logical clock (3 digits), not wall time.
9. Uppercase enforcement on `program_enrollments`/`categorical_exclusions` entries.
10. PATCH `/chw/patients/{id}` with an empty body still bumps `version`.
11. Unmatched routes return `ERR_RESOURCE_NOT_FOUND`/404 in the envelope.
12. `reversal_reason` defaults to `MANUAL_REVERSAL` when omitted; `ENCOUNTER_VOIDED` only from the void cascade.

**Orchestrator independent verification of Steps 5+6:** `def test_` = 101 == `Design:` tags = 101; zero pytest skip/xfail markers (5 `skip`-word hits all English prose in docstrings/PRD quotes); impl persistence grep (`sqlite|pickle|shelve|json.dump|open(...,'w')|/tmp`) empty; live `app.url_map` = 70 routes excluding `/static` (44 POST, 25 GET, 1 PATCH).

## Step 7: Run tests and iterate — 2026-08-03T19:45:00.000Z

Clean 8-round sweep. Exiting.

## Summary

**Iterations run:** 2 (sweep → 1 test fix → sweep).

**Final sweep, per-round passed/total** (all 8 rounds, 4 waves of 2): rounds 1–8 all **101/101**. 0 skipped, 0 errors, 0 restart failures across all 8 rounds.

**Tests deleted:** none.

**Fixes applied to `test_suite/`:**
- `test_04_resource_network_and_eligibility.py` — `test_income_failure_is_reported_before_geography_failure`: the `evaluated_count` assertion expected `1` ("evaluation stops at the first failure"), which traces only to `SCAFFOLD_CORNER_DESIGN.yaml:1170`/`:1215` and is **contradicted by PRD prose**. PRD §3.3 states verbatim: *"The response reports `eligible` as a boolean, `evaluated_count` as the number of criteria in the ordered list, and three fields describing the stopping point: `first_failing_criterion_id`, `first_failing_criterion_type` and `first_failing_error_id`…"*. The offering carries two criteria (INCOME_BAND + GEOGRAPHY), so the PRD-mandated value is `2`. Per STEP 1c, corrected the assertion to `== 2` and added the governing PRD quote to the docstring; the covered assertions (`eligible is False`, `first_failing_criterion_id`, `first_failing_criterion_type == "INCOME_BAND"`, `first_failing_error_id == ERR_ELIGIBILITY_INCOME` — i.e. rank-1 income pre-empting rank-2 geography, the corner instance's actual claim) were all kept intact. Note `SCAFFOLD.yaml:2000` (`return PASS(evaluated_count = len(order))`) agrees with the PRD, so the corner-design instance was internally inconsistent with its own scaffold calc.

**Fixes applied to `test_helpers/`:** none.

**Fixes applied to `implementation/`:** none. `routes_resources.py:203` (`"evaluated_count": len(order)`) was already PRD-faithful.

**Non-failure noted and dismissed:** rounds 1 and 2 of the FIRST sweep both hit `ERROR at setup … API server could not be restarted` on `test_02::test_placing_a_hold_lapses_sent_referrals_and_releases_their_units`, at the same wall-clock instant (19:19:03) with `port-registry … holders=5`. Co-tenant host saturation during the per-test server reboot, not a defect — no change made on that evidence; did not recur in rounds 3–8 or anywhere in the final sweep.

**Orchestrator independent verification of the final sweep:** all 8 `results.N.json` present and parseable, each with **101 individual test rows** (not just an aggregate), status distribution `{'passed': 101}` in every round, `failed=0 skipped=0 errors=0` in every round, and sorted test-name lists **byte-identical to round 1 in all 7 comparisons**.

## Step 8: Finalize PRD — 2026-08-03T19:52:00.000Z

`workspace/PRD_FINALIZED.md` created and is **byte-identical to PRD.md** (md5 `87c4f6b96237a28233b91ee62d6b3182` for both).

## Line counts / delta
PRD.md 487 lines / PRD_FINALIZED.md 487 lines. **0 lines changed, 0.0% delta — the patch is empty (intentionally).**

## Changes
**None.** The single `<step_7_diff>` item is a pure test bug; PRD §3.3 already uniquely determines the implementation's behavior, so no edit was warranted.

## Pre-edit search log (run for the one diff item; concluded no-edit)

**(a) Subject:** the `evaluated_count` value and the `first_failing_criterion_id`/`_type`/`_error_id` triple returned by the eligibility-check dry run, and whether short-circuit evaluation truncates the count.

**(b) Impl paths enumerated:**
- `calc.py:176-180` `ordered_criteria()` returns **all** criterion rows for the offering, sorted `(evaluation_rank, created_at, _seq)`; no status filter.
- `calc.py:183-213` `run_gauntlet()` short-circuits on first failure but returns the **full** `order` list in every branch.
- `routes_resources.py:186-207` — the **only** emitter of `evaluated_count`/`first_failing_*` (grep-confirmed single site); `len(order)` regardless of stopping point; all three `first_failing_*` are `None` when `failing is None`.
- `routes_referrals.py:37-42` `_eligibility_step`, wired at rung 12 for both referral create (`:129`) and re-route (`:262`) — discards `_order`, raises only `error_id`; no second consumer of the count.
- `routes_resources.py:174-183` `list_criteria` uses the same `ordered_criteria()` helper, so "the ordered list" is literally the listing companion's list.
- Criterion endpoint inventory is create + list only — no delete/deactivate, so "criteria attached to the offering" is unambiguous and monotonic.

**Determination:** PRD.md:258 states verbatim "`evaluated_count` as the number of criteria in the ordered list", with "the ordered list" defined at PRD.md:248. Every candidate referent denotes the same full set and yields `len(order)`. The short-circuit value `1` is reachable only by substituting "criteria evaluated" for the words actually written — a misreading, not an admitted ambiguity. Zero-criteria case pinned at PRD.md:248; all-pass path pinned by "When `eligible` is true, all three of those fields are null", matching `run_gauntlet`'s `return order, None, None`.

**(c) Wording adjustment:** none — no edit committed. A clarifying gloss would have been a manufactured edit against an already-determined rule.

## Step 9: Complete PRD — 2026-08-03T20:08:00.000Z

`workspace/PRD_COMPLETED.md` produced from `PRD_FINALIZED.md`.

- **Lines:** 487 → 496 (+9). **Chars:** 103,760 → 121,138 (**+17,378**).
- **Changes:** 44 edits — **38 ambiguity-pins**, **6 mismatch-revisions**. No new sections; all 107 table rows and every heading preserved.

### Mismatch-revisions (PRD asserted something impl does not do)
- **§2.4** — revise — "Timestamps … rendered with exactly three fractional-second digits" was false for most fields. Pinned the three-class rule: `created_at`/`updated_at`/`api_request_timestamp` = 3 digits; every other server-written instant reproduces the clock's operator string **verbatim**; arithmetic-derived stamps inherit their source's style; caller-supplied instants echo verbatim — `clockutil.py:3-12,44-63`.
- **§2.5 ¶ after rung 17** — revise — "relative order within a rung is immaterial … with one exception" was wrong: pinned four intra-rung orderings (eligibility rank; uniqueness-last at rung 5; per-endpoint rung-6 dangling-ref order; **suspension before enrollment at rung 9**) — `routes_referrals.py:51-57`, `routes_config.py:64-66`.
- **§3.3** — revise — `released_units` was said to accumulate from a "closed-without-delivery referral"; closing releases nothing — `routes_referrals.py:212-229`.
- **§3.4 (reroute)** — revise — "written onto **every** referral row sharing the same `root_referral_id`" — impl excludes the new child, which stays at `version` 1 — `routes_referrals.py:270-275`.
- **§3.4 (preconditions)** — revise — precondition order swapped to org-suspension-first — `routes_referrals.py:51-57`.
- **§2.1** — revise — "first check … before it looks at the path" — an unmatched route 404s (and a bad method 405s) before any header check — `app.py:44-51`.

### Ambiguity-pins (38, by vein)
- **Version granularity (§2.4, §2.11, §3.1, §3.2, §3.4):** one bump per row per request however many cascade links reach it; rows created by the request stay at 1; patient PATCH bumps once even for demographics + enrollment together; an empty PATCH body is a no-op that still bumps; records-hold cascade raises `unfulfilled_referral_count` N times but `version` once — `store.py:73-103`.
- **Cascade legs that don't fire (§3.1, §3.4, §3.5, §3.7, §3.8, §3.9, §3.10):** `RELEASE` fires no cascade; DISENROLL skips non-`ACTIVE` goals; restore-and-auto-resolve skipped when the offering was never exhausted; `ACKNOWLEDGED`/`RESOLVED` escalations never auto-resolved; VOID cascade skips non-`DRAFT` encounters; non-grant-locked void runs no cascade; UPHELD/reversal skip encounters no longer `LOCKED`; a sweep matching nothing writes nothing.
- **List ordering (§2.3, §3.10):** ties broken by **server creation sequence**, never `id` — critical because the standing logical clock collides `created_at`; same tie-break in criteria order and sweep processing order.
- **Echoed entity (§2.11):** reroute→child (201), reversal→line, void→encounter, records-hold→patient, claim/line→itself.
- **Query filters (§2.3):** exact case-sensitive strings, **never enum-validated** (off-enum ⇒ empty page, not 400); empty-string `limit`/`offset` = absent; `has_more` formula. Contrast pinned at §3.10: the report's `denominator_basis` **is** enum-checked.
- **Serializer (§2.4, §2.2):** full declared field set always present, `null`/`[]` never omitted; four endpoints return derived non-entity objects with no `id`/`version`.
- **Errors (§2.1, §2.5):** framework errors wrapped in the envelope; malformed/absent body = `{}`; undeclared body fields ignored (incl. `mrn`, `full_name`, `evaluation_rank`, `offering_id`).
- **Optional defaults (§3.1, §3.3, §3.4, §3.5, §3.8):** hold `reason`→null; criterion own-type fields→null/`[]` **and then pass trivially** (empty `allowed_zips` fails everyone); `decline_reason`/`denial_reason` ignored on the non-firing branch; doc-revision `visit_note` **absent ≠ null** (absent preserves, null clears).
- **Boundaries (§3.5, §3.8, §3.10):** 72h / 30d / 60d / 365d are exact elapsed durations, not calendar units.
- **Rounding (§2.9):** figures travel as JSON numbers — 25.00 ⇒ `25.0`, 62.50 ⇒ `62.5`.
- **Role/ownership (§3.4, §3.6):** reroute has **no** ownership check and the child inherits the parent's `opened_by_chw_id`; goal-progress has **no** state precondition and **no** ownership check — it works on closed goals without reopening them.
- **Unenforced attributes (§3.2, §3.3):** instrument `effective_from` and org `service_zips` are recorded but never consulted; `unit_type` unconstrained by `org_type`.
- Plus: `ERR_PATIENT_NOT_ENROLLED`/rung-9 named for goal-create, goal-reopen, visit-create, encounter-create; `travel_miles` stored unquantized; linked home visit need not share the patient; report scoping (only minute figures use `service_month`).

### Veins that came back CLEAN (already uniquely pinned)
**#10 boundary inclusivity** (every comparison site — half-open slots, closed grant periods, `>=` tiers, `== 2` escalation threshold — already correct and unambiguous; only the *units* of the duration windows needed pinning) and **#11 rounding order** (per-encounter vs monthly mileage, round-then-sum, twice-and-independently, clamp-after-round all exact). **#12's gate roster** was also clean — the 19 gated / exempt lists in §2.6 match `gated=True` in the implementation exactly, with no summary-vs-detail drift; §5's 33-row error catalogue matches `errors.py` one-for-one, and §4's endpoint/role table matches every `Endpoint(...)` declaration.

**Orchestrator independent verification:** `PRD.md` and `PRD_FINALIZED.md` md5-identical (`87c4f6b9…`); `PRD_COMPLETED.md` 496 lines / 120,765 chars vs 487 / 103,469 — headings 29→29 and table rows 107→107 preserved, so no section was dropped or duplicated; implementation still boots with 70 routes after Step 9.

---

# PIPELINE COMPLETE — task_0918_chw_sdoh_program

**101/101 tests passing on all 8 sweep rounds, 0 deletions, 0 implementation fixes.** 4th-generation beyond-Expert recipe; Step 8 empty by design, Step 9 = 44 edits.
