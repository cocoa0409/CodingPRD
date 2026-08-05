# Worklog — task_0916_hospital_at_home_program

Scenario (verbatim): `916. Hospital-at-Home Program: eligibility & admission criteria, remote-monitoring & device kit, nurse/paramedic visit & telehealth rounding, medication & DME delivery, escalation & bed-return, meals & care coordination, CMS-waiver billing, discharge`

Difficulty: **beyond-Expert** (user request: "generate task hard than expert level").

## Step 1: Create task directory — 2026-08-03T15:10:00.000Z

Created `tasks/task_0916_hospital_at_home_program/` and `tasks/task_0916_hospital_at_home_program/workspace/`. Index 0916 = highest existing (0915) + 1.

## Step 2: Generate scaffold — 2026-08-03T15:58:00.000Z

All three artifacts are generated, YAML-valid, and lint-clean.

## Output

- `/home/ubuntu/github/CodingPRD/tasks/task_0916_hospital_at_home_program/SCAFFOLD.yaml` (3061 lines)
- `/home/ubuntu/github/CodingPRD/tasks/task_0916_hospital_at_home_program/SCAFFOLD_DIFFICULTY_DESIGN.yaml` (1622 lines)
- `/home/ubuntu/github/CodingPRD/tasks/task_0916_hospital_at_home_program/SCAFFOLD_CORNER_DESIGN.yaml` (2687 lines)

## Density achieved

| Metric | Target | Actual |
|---|---|---|
| Entities | 13–15 | **15** |
| Endpoints | 50–62 | **60** |
| Error codes | 26–32 | **32** |
| State machines | 8–10 (≥4 non-linear) | **10, of which 9 non-linear** |
| Calculations | 8–10 (≥4 dual-variant) | **10, of which 5 dual-variant** |
| Validations | 26–32, ladder ≥12 rungs | **31 on a 16-rung ladder** |
| OCC rules | 2–3 distinct entities | **3** (DeviceKit, InpatientUnit, Episode) |
| Conservation invariants | ≥1 | **3** |
| Deepest cascade | ≥4 | **depth 5, 4 downstream entity kinds** |

**Non-linear machines**: Episode (cyclic bed-return→readmit), Visit (parallel scheduling × attestation axes), DailyComplianceRecord (cyclic finalize↔reopen), DeviceKit (cyclic refurb loop), DeliveryOrder (branching + capped redelivery), MealPlan (cyclic suspend↔resume), EscalationEvent (branching 4-tier ladder with SLA auto-promotion), BillingClaim (cyclic capped appeal loop), BedReservation (branching occupy/release/expire). Only Referral is linear.

**Dual-variant calcs** (5, all different entity domains): `daily_visit_compliance` (waiver vs FFS), `episode_reimbursement_amount` (per-diem vs DRG-equivalent), `delivery_handling_fee` (controlled vs non-controlled), `escalation_sla_deadline` (HIGH vs STANDARD acuity), `meal_credit_accrual` (waiver-bundled vs FFS-billed). Combinatorial modes (a)/(b)/(c) are all covered: nested `min(max(...))` floor/cap, pinned round-per-visit-then-sum (31.12 vs 31.11), and a circular-looking withhold whose tier is pinned to gross not net.

**Deepest cascade (C1, depth 5)**: `convert-bed-return` → EscalationEvent BED_RETURN_CONVERTED → Episode RETURNED_TO_FACILITY → DeviceKit IN_REFURB → DailyComplianceRecord CARVED_OUT → BillingClaim VOIDED. Three shorter cascades from different triggers (visit amendment, discharge, delivery abandonment).

**Conservation invariants**: episode day ledger (`service = billable + carved_out + pending`), kit census (`total = available + deployed + in_refurb + retired`), bed census (`total_beds = available + held + occupied`).

**Instances**: 19 difficulty (9 rules × 2, plus a third combinatorial mode), 59 corner (50 with full recipes + 9 `excluded_because` stubs).

## Audits run

- **Undeclared-constant sweep**: 48 declared constants; zero ALL_CAPS tokens matching WINDOW/BUFFER/LIMIT/MAX/MIN/THRESHOLD/RADIUS/SLA/CAP/RATE/FEE/USD/… lack a numeric value. All boundary comparisons state inclusive/exclusive in words.
- **`scaffold_lint.py`**: `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` (785 calls scanned, 60 endpoints, 15 entities).
- **Grounds resolution**: 0 dangling refs. **Name uniqueness**: 0 duplicates across both design files. **Placeholder closure**: 0 unbound `${var}`. **Stub targets**: all 9 cite existing §1.8 instances. **Error triggerability**: all 32 codes referenced. **Forbidden concurrency vocabulary**: none.

## Two reachability defects found and fixed during generation

1. **`ERR_REDELIVERY_LIMIT_EXCEEDED` was unreachable** — the original `refuse`-at-cap→FAILED edge consumed the only state where the dispatch cap could bite. Restructured: `refuse` from `OUT_FOR_DELIVERY` always yields `REFUSED`; the third dispatch is rejected by the cap leaving the order `REFUSED`; a follow-up `refuse` from `REFUSED` (with `redelivery_count == 2`) abandons it to `FAILED`. Both outcomes now reachable.
2. **`KIT_NOT_DEPLOYED` carve-out reason was unreachable** — clause 1 (insufficient visits) always failed first on the bed-return date. Fixed the kit-release side effect to run the standard ordered clause evaluation, and extended the C1 setup so 2026-06-02 carries two attested in-person visits plus a telehealth physician evaluation — so clauses 1–3 pass and only the kit clause fails.

I also lowered `NON_CONTROLLED_HANDLING_BASE_USD` 18.00→12.00 (otherwise the 15.00 fee floor was unreachable) and `CLAIM_WITHHOLD_TIER_THRESHOLD_USD` 10000.00→9600.00 (so the inclusive tier boundary lands exactly on a naturally-producible gross).

**Orchestrator verification**: all 3 files `yaml.safe_load` clean; SCAFFOLD.yaml parses to 15 entities / 60 endpoints; independent ALL_CAPS sweep found 18 residual tokens, all of which are enum members, error codes, or valued inline (`SECONDS_PER_MINUTE: 60` at SCAFFOLD.yaml:1679) — 0 genuinely undeclared constants.

## Step 3: Copy INSTRUCTION.md — 2026-08-03T16:00:00.000Z

Copied `./INSTRUCTION.md` → `tasks/task_0916_hospital_at_home_program/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-08-03T16:14:00.000Z

PRD generated at `workspace/PRD.md`. **429 lines**, written across 8 bounded Write/Edit calls (no single giant write).

**Section list**
- §1 Introduction (3 paragraphs)
- §2 Global Specifications — 2.1 Care-Team Identity and RBAC · 2.2 API Response Structure (verbatim) · 2.3 Pagination and List Ordering · 2.4 Record Identity, Audit Timestamps and the Program Clock · 2.5 The Rejection Ladder · 2.6 Optimistic Concurrency on Shared Inventory and Ledgers · 2.7 Money, Minutes and Rounding Discipline · 2.8 Conservation Invariants · 2.9 Cascade Discipline and Version Propagation · 2.10 Controlled Vocabularies
- §3 Business Logic — 3.1 Referral→Eligibility gauntlet · 3.2 Admission and the Day Ledger · 3.3 Visits (two independent axes) · 3.4 Monitoring, Telemetry Gaps and the Daily Verdict · 3.5 The Monitoring Kit · 3.6 Delivery Under Chain-of-Custody · 3.7 Meals and Care Coordination · 3.8 Escalation, the Held Bed, and Coming Back Home · 3.9 Discharge, Claim Construction and Payer Settlement
- §4 Endpoint Definitions (60 rows, 4 columns) · §5 Error Code Catalogue (32 rows, 2 columns)

**Self-audit (mechanically verified)**

- (a) **60 endpoints** — all 60 in the §4 table, verified against the scaffold's endpoint list; role columns copied per-endpoint. Path params 1/1. Query params 10/10 present in backticks.
- (b) **32 error codes** — all 32 named in §2/§3 prose *and* tabulated in §5; 0 missing.
- (c) **47 program constants** — all stated with values. Three rendered in words rather than digits by design (high-acuity multiplier "halved and then rounded half up" plus explicit derived 5/10/15/8 minutes; delivery cap "one-hundred-and-twenty-dollar cap"; bed hold "`held_at` plus one hundred and twenty minutes"). All three pass the reconstruction test; the other 44 appear numerically.
- (d) **10 state machines** — all 51 distinct state names present; every transition rendered with both branches. Explicitly symmetric pairs: finalize COMPLIANT vs CARVED_OUT (added money-recompute to the carve-out branch), close-unperformed NO_SHOW vs CANCELLED (incl. discharge-time finalization on the CANCELLED branch), attest reopen-from-COMPLIANT vs reopen-from-CARVED_OUT, kit IN_REFURB→AVAILABLE vs →RETIRED, meal plan discharge COMPLETED vs CANCELLED, claim PAID-from-SUBMITTED vs PAID-from-APPEALED, dispatch from AUTHORIZED vs redelivery from REFUSED, refuse from OUT_FOR_DELIVERY vs abandonment from REFUSED.
- (e) **10 calculations** — each with rounding rule and pinned order: travel (round per visit *then* sum), delivery fee (weight rounded before sum; floor *then* cap), claim (gross → rate keyed on gross → withhold → net), lapse minutes (floor), SLA minutes (round half up), plus day-verdict clause order, day-ledger aggregation, reimbursement dual-variant, meal accrual dual-variant, kit census.
- (f) **Validation ladder** — §2.5 renders all 16 rungs as an explicit numbered list, with intra-rung ordering spelled out for rungs 4, 9, 11, 14, 15, each rule's `error_id`, HTTP status and full `applies_to` endpoint set.

**Hard Contracts**

```
Field coverage check:
- entities[].fields: 114 required, 114 present, 0 missing
- endpoints[].request_body: 54 required, 54 present, 0 missing
- endpoints[].query_params: 10 required, 10 present, 0 missing
- endpoints[].path_params: 1 required, 1 present, 0 missing
Status: PASS

Rule coverage check:
- validations[] with priority: 31 checked, 31 expressed in prose, 0 missing
- concurrency_rules[] OCC rejections: 3 checked, 3 expressed (write_endpoint + expected_<parent>_version + ERR_STALE_VERSION/412 all named), 0 missing
- state_machines[].transitions: 47 checked, 47 fully expressed, 0 missing
- calculations[]: 10 checked, 10 fully expressed, 0 missing
- validations[] conditions: 31 checked, 31 matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: 60 checked, 60 expressed, 0 missing
- entities[].fields[] structured content: 114 checked, 114 reconstructible from prose, 0 missing
- sibling-branch symmetry: 8 groups checked, 8 with equal prose density, 0 asymmetric
Status: PASS

Path purity check (§3 only):
- backtick tokens scanned: 884
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

Also verified: §2.2 matches `section-2.2-response-structure.md` byte-for-byte; all 8 role names and all 101 enum values present verbatim; no audit footer in the file (it ends at §5).

Two judgement calls worth flagging, both resolved toward the literal endpoint contract: (1) a *failed* mark-eligible writes `first_failed_gauntlet_rung` and therefore advances the referral's `version`/`updated_at`; (2) escalation acknowledge/promote deadline violations map to `ERR_INVALID_STATE` (409), the only code the catalog offers for a failed transition precondition. Per-tier acknowledgement actors are documented as advisory, not as an RBAC gate — the endpoint's authorized-role list governs.

**Orchestrator verification**: PRD.md = 429 lines; §4 table contains exactly 60 method+path rows.

## Step 5: Generate unit tests — 2026-08-03T16:42:00.000Z

Test infrastructure and suite are complete and mechanically verified.

**Totals**: **89 tests** across 12 test files, 0 collection errors, 0 pyflakes findings (outside the intentional barrel re-export), **0 `skip` / `skipif` / `xfail` markers**.

**Queue A — difficulty index (19 instances)**: **19/19 translated, 0 skipped.** Every instance carries ≥2 tests (39 queue-A tests total; the depth-5 bed-return cascade got 3 — escalation+episode, kit release + `KIT_NOT_DEPLOYED` carve-out, claim void + meal/delivery/ledger settlement).

**Queue B — corner index (59 instances)**: **50/50 non-stub translated, 0 skipped** (50 queue-B tests). The 9 `excluded_because` stubs were verified to cross-reference real §1.8 instances and were correctly **not** emitted.

Nothing failed the PRD-first two-condition filter — every instance's rule is verbatim in PRD and uniquely derivable, largely because §2.5 renders the 16-rung ladder explicitly (so priority-ordering assertions are contract-backed rather than scaffold-only).

**test_helpers modules written**
- `types.py` (453 L) — 22 enums + 15 entity TypedDicts; `MonitoringLapse` correctly omits `updated_at`/`version` (`common_fields: false`)
- `api_client.py` (322 L) — 60 endpoint methods over `GenericApiClient`
- `api_errors.py` (80 L) — 32 error ids + status map, registered with the framework
- `assertions.py` (435 L) — per-entity assertions, three conservation-invariant checkers, `assert_money`
- `factories.py` (195 L) — 15 payload factories with a monotonic `unique_suffix()` for `mrn`/`asset_tag`/`serial_number`/`unit_code`
- `constants.py` (92 L) — every PRD-stated threshold and rate
- `test_users.py` (82 L) — 7 opaque-role constants **plus per-instance builders for all 8 roles**; `make_patient_headers(patient_id)` is mandatory for the entity-backed `Patient` role
- `fixtures.py` (907 L) — 5 tiers: primitives → admission funnel → visit/day helpers → escalation-ladder walker → terminal-state and revenue-cycle composites, including `setup_bed_return_cascade()`
- `__init__.py` — barrel export

**Verification performed**: a custom audit script (AST + YAML) confirmed for all 89 tests: exactly one trailing `Design:` line, every tag resolving to a real non-stub instance, and **every quoted PRD citation surviving a whitespace-normalised literal match against PRD.md** (0 non-verbatim citations, 0 citations under 8 words).

**Two notes for the implementation phase**
1. **Timestamps are compared as instants.** `assertions.parse_instant` / `assert_same_instant` parse both sides, so `2026-06-02T13:03:00.000Z` and `...Z` compare equal — this neutralises the recurring impl-gen rendering defect. Raw-string equality is used only for `service_date` / `activated_on_date` (`YYYY-MM-DD`, pinned in PRD prose).
2. **Identity threading is real.** Visit actions are issued under `make_<role>_headers(staff_user_id)` so `attested_by_user_id` lands on the owning clinician; the segregation-of-duties tests use genuinely distinct `pharm-9` / `pharm-7` authorizers; and no test seeds state by any route other than the 60 declared endpoints (fixtures use `get_success_data` throughout, so setup breakage surfaces as a clear failure rather than a confusing assertion).

**Orchestrator verification**: `def test_` count = 89, `Design:` tag count = 89 (1:1). The only 4 `skip` string hits in the tree are the English word "skips" inside docstrings — 0 pytest markers.

## Step 6: Generate implementation — 2026-08-03T16:41:00.000Z

Implementation complete and verified. `workspace/implementation/` — Python + Flask, **3,452 lines across 30 files**, in-memory only.

| Module | Lines | | Module | Lines |
|---|---|---|---|---|
| `app.py` | 93 | | `routes/episodes.py` | 172 |
| `calc.py` (10 calculations + constants) | 236 | | `routes/visits.py` | 183 |
| `clock.py` (logical clock + rendering) | 140 | | `routes/deliveries.py` | 166 |
| `derived.py` (all computed fields) | 249 | | `routes/referrals.py` | 159 |
| `ladder.py` (16-rung ladder) | 288 | | `routes/device_kits.py` | 133 |
| `serializers.py` | 270 | | `routes/claims.py` | 130 |
| `store.py` | 163 | | `routes/escalations.py` | 112 |
| `errors.py` (32 codes) | 121 | | `routes/beds.py` | 98 |
| `envelope.py` | 80 | | `routes/patients.py` | 89 |
| `domain/` (episodes, kits, compliance, beds, meals, escalations) | 383 | | `routes/` (meal_plans, monitoring, common, clock) | 187 |

**A. Route-count gate — PASSED.** Ran programmatically (`yaml.safe_load` of `endpoints[]` vs `app.url_map`, normalized to `METHOD /path`): `EXPECTED: 60   REGISTERED: 60   MISSING: 0   EXTRA: 0`.

**B. Adjudication of the two recurring bugs**

1. **Timestamp rendering.** One explicit rule, documented in `clock.py`'s docstring: caller-supplied instants (`in_person_eval_at`, `scheduled_*_at`, `gap_*_at`, `to_iso8601`) are echoed **verbatim**; `Episode.physician_eval_at` copies the assessment string verbatim so it never drifts. `created_at`/`updated_at`/`api_request_timestamp` use **one** rendering, 3 fractional digits (PRD §2.4 states this literally for those two fields). All other server stamps (`admitted_at`, `returned_at`, `discharged_at`, `deployed_at`, `finalized_at`, `held_at`, `occupied_at`, `tier_entered_at`, `current_utc`) render the logical clock in the **exact textual style the operator set it to** — set the clock to `2026-06-01T08:00:00Z` and `admitted_at` comes back as `2026-06-01T08:00:00Z`, not `.000Z`. Derived instants preserve their source's style: `hold_expires_at` from `held_at`, `ack_deadline_at` from `tier_entered_at` (`clock.plus_minutes`).
2. **Enum-membership routing.** `ERR_INVALID_ENUM` (422) **does** exist in this catalogue, so **every** enum-membership failure routes to it — not just the fields PRD names. A single helper `ladder.check_enum` is the only path to that code, used for all 17 enum inputs including the three narrowed `outcome` fields. Numeric/format/ordering bounds and missing-required stay on `ERR_VALIDATION` (400); no enum failure ever lands there.

**D. Self-verification results**
- `py_compile`: 30/30 files, **0 errors**.
- Persistence grep (`sqlite|json.dump|pickle|open(|/tmp|shelve|redis|sqlalchemy|.db`): **no matches**. Only Python dicts.
- Error-code coverage: **32/32** catalogue codes present in source.
- Boot smoke: `bash start.sh` with `PORT` set → ready in **0.52 s**, bound to `0.0.0.0`, foreground `exec`. `POST /patients` returns 201 with the exact PRD §2.2 envelope.
- Fresh-boot empty store: census all zeros, `total_count` 0 everywhere, clock at `2026-05-01T00:00:00Z`. Nothing seeded.
- RBAC audit (60 endpoints × 8 roles = 480 probes vs scaffold `roles[]`): **0 mismatches**.
- Two behavioural smoke suites, ~150 assertions, all passing on fresh boots — covering: gauntlet ordering + all 7 boundaries, eval-window inclusivity (exactly 24 h passes, 24 h 01 m fails), radius 40.0/40.1, the 15-vs-14-minute turnaround buffer, travel banding + unconditional 8.00 telehealth floor, lapse interval-merge with zero-gap adjacency (60 min from two 30-min gaps), the 240/241-minute threshold, both track forks scoring the identical visit set differently, `KIT_NOT_DEPLOYED` reachable only as clause 4, the depth-5 bed-return cascade, readmission, redelivery cap → abandonment → C3 escalation, appeal cap + 60 % recovery, claim VOIDing on carve-out, lazy bed expiry (at-expiry still HELD, +1 s EXPIRED), DRG outlier days, and ladder precedence (role > body schema, path > body FK, FK > OCC, OCC > fiscal, episode-gate > capacity, witness > cold-chain, med-rec > delivery).

**Notable interpretation decisions**
- **Version bumps** use a per-request dirty set: each row mutated — including cascade-reached rows — bumps exactly once. Episode and InpatientUnit additionally bump when their *derived* roll-ups change, which PRD §2.4 names explicitly. `DeviceKit.component_count` refresh deliberately does **not** bump the kit — PRD §3.5 says "refreshes" without version language, and the corner design confirms a deploy anchored to the pre-component-add version must succeed.
- **A failed `mark-eligible` still commits** the `first_failed_gauntlet_rung` write and its version bump before returning 422, per PRD §3.1.
- **No ownership rejection** is implemented for the `Patient` role: the ladder is declared exhaustive at 16 rungs and no ownership rule or error code exists in either the validations table or the catalogue.
- `MonitoringLapse` emits only `id`, `created_at`, `episode_id`, `gap_start_at`, `gap_end_at`, `cause` — no `updated_at`, no `version` (PRD §2.4).

**Orchestrator verification**: independent `app.url_map` diff vs scaffold `endpoints[]` → 60 expected / 60 registered (the only apparent deltas were path-param *names*, `{id}` vs `{episode_id}`, which do not affect runtime matching; plus Flask's built-in `/static`). Persistence grep over `implementation/**/*.py` = 0 hits. `start.sh` execs `python3 app.py` in the foreground after a conditional dependency install.

## Step 7: Run tests and iterate — 2026-08-03T16:47:00.000Z

All 8 rounds green on the first sweep, and the false-clean checklist confirms it is a real clean, not a silently-truncated suite.

**Iterations run: 1** (one 8-round stability sweep, two waves of four). Zero fixes and zero deletions were required — the implementation and test artifact were already mutually consistent and PRD-faithful.

- **Tests deleted:** none. No test failed in any round, so no test entered the STEP 1 coverage / unique-derivability filter.
- **Fixes applied to `test_helpers/`:** none.
- **Fixes applied to `test_suite/`:** none.
- **Fixes applied to `implementation/`:** none.

**Clean-sweep verification numbers** (the anti-false-clean checks):

| Check | Result |
|---|---|
| `results.N.json` present & parseable, N=1..8 | 8/8 |
| Individual test rows per file (not just a counter) | 89 rows in every round |
| Row status distribution per round | `{'passed': 89}` — 0 failed, 0 errors, 0 skipped, 0 duplicate names |
| Test-name SETS identical across all 8 rounds | True (set size 89, byte-identical sorted lists vs round 1) |
| Runner `collected` line in each `round.N.log` | `collected 89 items` in all 8 |
| Log tail per round | `89 passed, 0 failed, 0 errors, 0 skipped` ×8 |
| AST `def test_` count in `test_suite/` | 89 — equals collected count |
| Per-file counts (source AST vs results rows) | match across all 12 test files (11/9/5/9/6/6/9/7/9/6/5/7) |
| `pytest.mark.skip` / `skipif` / `xfail` / `pytest.skip(` | none — the pass is not achieved by skipping |
| Round wall-clock | 106s (wave 1, 4 concurrent) / 80s (wave 2) — consistent with ~89 server boots each, not a short-circuited run |

The single `Killed` line in each `round.N.log`, appearing right after test #1's name, is the documented benign artifact of the runner SIGKILLing the pre-boot server as per-test isolation swaps in a fresh one — not a crash.

**Independent cardinal-rule spot-checks**: a persistence/seed grep over `workspace/implementation/**/*.py` for `sqlite|sqlalchemy|shelve|redis|pickle|json.dump|json.load|open(|/tmp|.db` returns only two hits, both false positives from `open(` matching the substring in `compliance.reopen(` (`domain/compliance.py:61`, `routes/visits.py:171`). Storage is in-memory dicts only; nothing is seeded at startup.

Reusable artifact: `workspace/sweep.sh` (two waves of four, verbatim `cd $IMPL && bash start.sh`, no `pkill`).

**Orchestrator verification** (independent re-parse of all 8 result files, not trusting the subagent's report): 8 files, each `passed=89 total=89` with **89 individual rows**, status distribution `{'passed': 89}`, and sorted test-name lists identical to round 1 in all 7 comparisons.

## Step 8: Finalize PRD — SKIPPED — 2026-08-03T16:50:00.000Z

Skip condition met: Step 7 exited on the first 8-round sweep with **0 deletions, 0 `test_suite/` fixes, 0 `test_helpers/` fixes, and 0 `implementation/` fixes** — zero iterations beyond the baseline. There is no `<step_7_diff>` to hand off, so `PRD.md` already determined every behavior the tests exercised. No `PRD_FINALIZED.md` is produced; Step 9 starts from `PRD.md`.

## Step 9: Complete PRD — 2026-08-03T17:00:00.000Z

Full sweep of all 30 implementation modules (60 endpoints) against the PRD, with every behavior classified.

**Files**
- Source: `workspace/PRD.md` — 429 lines, 102,256 chars
- Output: `workspace/PRD_COMPLETED.md` — 429 lines, 113,194 chars (**+10,938 chars, 0 lines added**; all 32 touched lines are in-paragraph inserts/revisions, no new sections or paragraphs)

**Counts**: **32 ambiguity-pins**, **5 mismatch-revisions** (37 edits over 32 lines)

**Changes**
- §2.1 — revise — mismatch — impl performs **no ownership check at all** for the `Patient` role; a Patient-role caller is served any patient/episode/referral/visit its role list allows — `ladder.py:73`, `routes/patients.py:56`
- §2.2 — insert — ambiguity — `api_request_id` = `req_` + 20 uppercase-alnum; `api_request_timestamp` read from the **logical clock**, not wall clock — `envelope.py:16-24`, `clock.py:106`
- §2.3 — insert — ambiguity — filters compare as exact strings, off-enum/unmatched → empty page (not 400), empty value ignored, unknown params ignored; non-numeric `limit`/`offset` → `ERR_VALIDATION`, empty → default, offset past end → empty + `has_more` false — `routes/common.py:33-45`, `ladder.py:209-231`, `envelope.py:64-77`
- §2.4 — insert — ambiguity — **timestamp rendering rule**: `created_at`/`updated_at`/`api_request_timestamp` always 3 fractional digits; every other server-stamped instant reproduces the clock's *verbatim operator string*; derived instants inherit their source's digit style; caller instants echoed verbatim — `clock.py:82-114`
- §2.5 r1 — insert — ambiguity — empty header = absent; unrouted path/method → `ERR_RESOURCE_NOT_FOUND` before auth — `ladder.py:55`, `app.py:64-76`
- §2.5 r4a — insert — ambiguity — non-object/unparseable body = `{}`; undeclared body fields ignored — `ladder.py:82-86`
- §2.5 r4c — insert — ambiguity — uniqueness (`mrn`/`asset_tag`/`serial_number`/`unit_code`) and JSON-type violations are `ERR_VALIDATION` at this rung — `ladder.py:192`
- §2.5 r5 — insert — ambiguity — multi-FK failures resolve in the declared resource-type order — `routes/beds.py:57-58`
- §2.6 — revise — mismatch — a new claim does **not** supersede/void a prior `BUILT` claim — `routes/claims.py:42-55`
- §2.6 — insert — ambiguity — `expected_*` accepts an integer or an integer-valued string — `ladder.py:198-206`
- §2.8 — insert — ambiguity — all three balances derived at read time, never cached — `derived.py:133-229`
- §2.9 — insert — ambiguity — **version-bump granularity**: multi-touch row bumps exactly 1; rows created by the request stay at 1; roll-up parents bump only when a derived figure actually changes; failed requests bump nothing except the §3.1 bookkeeping write — `store.py:96-148`, `derived.py:234-249`, `routes/referrals.py:104-107`
- §3.1 — insert — ambiguity — explicit-null optional fields take the same default; duplicate `mrn` → `ERR_VALIDATION` — `routes/patients.py:40-49`
- §3.1 — insert — ambiguity — PATCH: omitted/null leaves value; version bumps even on a no-op patch — `routes/patients.py:73-76`
- §3.1 — insert — ambiguity — `mark-eligible` with no assessment → `ERR_INVALID_STATE` — `routes/referrals.py:79`
- §3.2 — insert — ambiguity — compliance days list in **mint order, not `service_date` order** — `routes/episodes.py:172`, `store.py:153`
- §3.2 — insert — ambiguity — the four counters + three money totals are evaluated live per read — `serializers.py:62-100`
- §3.2 — revise — mismatch — `sign-med-rec` has *no* state gate, `DISCHARGED` included; re-signing overwrites and bumps again — `routes/episodes.py:108-115`
- §3.3 — insert — ambiguity — new visit opens with `travel_payment_usd` 0.00 (field present from creation) — `routes/visits.py:88-91`
- §3.3 — revise — mismatch — `close-unperformed` never finalizes; the discharge cascade's own sweep does — `routes/visits.py:136-150`, `domain/episodes.py:66-72`
- §3.4 — insert — ambiguity — the three scoring inputs are read-time derivations; "recompute" writes nothing to the record; only finalize, reopen and the kit flag mutate it — `serializers.py:121-137`, `routes/visits.py:34-36`
- §3.4 — insert — ambiguity — null `cause` → `UNKNOWN`; a gap filed against an already-finalized date neither reopens nor rescores it — `routes/monitoring.py:42-46`
- §3.5 — insert — ambiguity — deploying a kit does **not** bump the episode's version — `domain/kits.py:11-20`
- §3.5 — insert — ambiguity — **cascade legs that don't fire**: no `DEPLOYED` kit → release is a total no-op; already-finalized current-day record → flag flips only, verdict stands — `domain/kits.py:31-49`
- §3.5 — insert — ambiguity — reconcile responds with the component, never the kit — `routes/device_kits.py:133`
- §3.6 — insert — ambiguity — cold-chain order with `excursion_minutes` omitted → `ERR_COLD_CHAIN_EXCURSION` (not a required-field error) — `routes/deliveries.py:135-138`
- §3.6 — insert — ambiguity — omitted optional handoff fields retain prior values; witness recorded even on non-controlled orders — `routes/deliveries.py:141-144`
- §3.6 — insert — ambiguity — abandonment responds with the failed order, not the spawned escalation — `routes/deliveries.py:159-166`
- §3.7 — insert — ambiguity — a `CANCELLED` plan still reports its `credited_day_count` while `meal_credit_total_usd` is 0.00 — `derived.py:183-187`
- §3.8 — insert — ambiguity — opening an escalation has no episode-state gate — `routes/escalations.py:25-39`
- §3.8 — insert — ambiguity — lazy expiry also bumps the **unit's** version, making a GET a write — `routes/beds.py:41-46`, `store.py:126-139`
- §3.8 — insert — ambiguity — bed-return with an expired hold: reservation left in `HELD`, no bed occupied, every other leg still fires — `domain/episodes.py:24-28`
- §3.8 — insert — ambiguity — convert responds with the escalation — `routes/escalations.py:112`
- §3.8 — insert — ambiguity — readmission neither redeploys a kit nor restores `kit_deployed_all_day` — `domain/episodes.py:87-93`
- §3.9 — insert — ambiguity — an episode that never had a kit clears gate 15c outright — `routes/episodes.py:141-145`
- §3.9 — insert — mismatch — prior `BUILT` claim left untouched by a rebuild — `routes/claims.py:42-56`
- §3.9 — insert — ambiguity — `denial_reason` requirement is a rung-4 `ERR_VALIDATION` judged before the state check; never cleared by a later `PAID`/`CLOSED` — `routes/claims.py:92-113`

**Category coverage**

*Found instances of*: per-entity response projections; list ordering (compliance days in mint order, not date order); version-bump granularity (8 distinct pins — the richest area by far); timestamp rendering (major silence — three distinct rendering styles); filter/query-param semantics; intra-rung routing order; non-firing cascade legs; optional-input defaults and null handling.

*Genuinely clean (no edit needed)*: money and minute **rounding order** at every call site — per-visit round-then-sum, weight-round→floor→cap, gross→rate-on-gross→withhold→net, floor-truncated lapse minutes, half-up SLA minutes all match the PRD's pinned orders exactly (`calc.py`); the global list sort/tie-break rule (`store.sort_key` matches §2.3 verbatim); the 8-rule gauntlet order; the 4 scoring clauses and track fork; the escalation tier table and HIGH-acuity halving; travel bands; per-diem/DRG arithmetic; the 3 conservation invariants; the full 32-code error catalogue and its HTTP statuses.

**Orchestrator verification**: `PRD_COMPLETED.md` present, 429 lines (same as source), 113,194 chars vs 102,256 — +10,938 chars with 0 line delta, consistent with in-paragraph-only edits.

---

# PIPELINE COMPLETE

`task_0916_hospital_at_home_program` — beyond-Expert. **89/89 tests passing on all 8 sweep rounds, 0 Step-7 deletions, 0 fixes of any kind.** Step 8 skipped; Step 9 supplied all 37 completeness edits.
