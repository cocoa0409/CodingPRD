# Worklog — task_2420_independent_practice_association_capitation_risk_pool_distribution

## Step 1: Create task directory — 2026-09-02T15:50:50.271Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2420_independent_practice_association_capitation_risk_pool_distribution` and its `workspace/` subdirectory. Index 2420 was pre-assigned by the orchestrating caller; no index scan performed (concurrent pipelines on this host).

## Step 2: Generate scaffold — 2026-09-02T17:36:03.760Z

Done. All three artifacts are complete and the linter is clean.

**Verbatim linter output** (`python3 /home/ubuntu/github/CodingPRD/skills/prd-bench-scaffold-generator/scaffold_lint.py /home/ubuntu/github/CodingPRD/tasks/task_2420_independent_practice_association_capitation_risk_pool_distribution`):

```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           tasks/task_2420_independent_practice_association_capitation_risk_pool_distribution/SCAFFOLD.yaml
  Difficulty design:  tasks/task_2420_independent_practice_association_capitation_risk_pool_distribution/SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      tasks/task_2420_independent_practice_association_capitation_risk_pool_distribution/SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    44
  §1.1 entities declared:     12
  §1.8 instances scanned:     20
  §1.9 instances scanned:     55
  Calls scanned (§1.8+§1.9):  1078

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

Files (all in `/home/ubuntu/github/CodingPRD/tasks/task_2420_independent_practice_association_capitation_risk_pool_distribution/`):
- `SCAFFOLD.yaml` — §1.0–§1.7 only (top-level keys: `scenario, domain_name, api_prefix, complexity_profile, response_envelope, entities, state_machines, concurrency_rules, calculations, validations, endpoints, errors, roles`; neither design key present)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single key `scaffold_difficulty_design`
- `SCAFFOLD_CORNER_DESIGN.yaml` — single key `scaffold_corner_design`

**Scaffold surface**: `domain_name: ipa-capitation-risk-pool`, `api_prefix: /ipa`, `difficulty_level: expert_plus`. 12 entities (DelegationAgreement, PhysicianMember, Enrollee, MemberAssignment, EnrollmentFile, EnrollmentFileRow, CapitationRemittance, RiskPool, DownstreamClaim, StopLossRecovery, QualityScorecard, PoolDistribution), 11 state machines, 2 §1.2.1 OCC rules, 12 calculations (2 dual-variant), 29 validation priorities, **44 endpoints** (24 GET / 19 POST / 1 PATCH), 42 error codes, 6 roles (`segregation_of_duties`, two entity-backed: PhysicianUser→PhysicianMember, PayerRepresentative→DelegationAgreement).

**§1.8 difficulty coverage**: all 9 rules, 20 instances — `dual_variant_calc 2`, `combinatorial_formula 3`, `non_linear_state_machine 2`, `transitive_cascade 2` (depth 5 and depth 4 chains), `priority_pair_validation_conflict 2`, `boundary_precision_check 3`, `cross_entity_state_dependency 2`, `resource_temporal_overlap 2`, `compensating_invariant 2`.

**§1.9 corner coverage**: all 9 claim-extraction-guide sections, 86 instances = **55 full recipes + 31 `excluded_because` stubs** — entities 12, state_machines 16, calculations 17, validations 13, endpoints 5, errors 8, rbac 5, cross_cutting_layers 8 (all four declared layers: `optimistic_concurrency` ×2 real, one per §1.2.1 rule; `rate_threshold_triggers` cumulative-attachment + reset; `cascading_side_effects` / `dual_variant_calculation` as stubs), consistency_model 2.

Verified beyond the linter: names globally unique across both design files; no stub carries a `test_recipe`; every `difficulty_instance` citation resolves to an existing `rule_id / name` pair; zero unresolved `${var}` placeholders across all 1078 calls and all `assert:` blocks.

One scaffold-wide change was needed to reach a clean lint: check (f) matches sub-resource reverse-reachability GETs only against the literal `{id}` placeholder, so all path templates were normalized from `{agreementId}`/`{fileId}`/etc. to `{id}` (no path contains more than one placeholder, so this is unambiguous) across all three files. Also reworded one Enrollee field description that used the word "Concurrent" to avoid the forbidden concurrency vocabulary.

## Step 3: Copy shared files — 2026-09-02T17:36:03.760Z

Copied `./INSTRUCTION.md` → `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-02T17:52:35.586Z

PRD complete and verified.

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_2420_independent_practice_association_capitation_risk_pool_distribution/workspace/PRD.md`

**Final line count:** 426 lines
**Exact final heading:** `## 5. Error Code Catalogue` (file's last line is the table row `| ERR_ALLOWED_EXCEEDS_BILLED | 422 Unprocessable Entity |` — a complete table row at a real section boundary, no audit footer, no truncation, no leftover build sentinel)

**Structure:** §1 Introduction; §2.1–§2.11 (2.2 byte-verbatim from `section-2.2-response-structure.md`, confirmed by exact string match); §3.1–§3.8; §4; §5.

**Hard Contract 1 — Field-Name Coverage: PASS.** All 12 entities' names appear; 0 of the entity `fields[].name` identifiers are missing from backticked prose. All `input`/`request_body`/`query_params`/`path_params` identifiers across all 44 endpoints appear verbatim in backticks, including every optional query filter and `current_utc`. The `settlement-preview` computed-read output struct is fully enumerated (`gross_claims_cents`, `stop_loss_recovery_cents`, `ibnr_reserve_cents`, `net_claims_cents`, `raw_surplus_cents`, `surplus_ratio_bps`, `surplus_tier`, `admin_fee_bps`, `admin_fee_cents`, `distributable_surplus_cents`, `shared_savings_pool_cents`).

**Hard Contract 2 — Rule Coverage: PASS.**
- All 29 validations enumerated in §2.10 with error ID, HTTP status and full `applies_to` set; both deliberate priority conflicts stated explicitly (priority 9 `ERR_PHYSICIAN_NOT_ACCEPTING_ASSIGNMENTS`/409 beats priority 27 `ERR_PANEL_CAPACITY_EXCEEDED`/422; priority 15 `ERR_ASSIGNMENT_BEFORE_COVERAGE`/422 beats priority 18 `ERR_ASSIGNMENT_PERIOD_OVERLAP`/409).
- Both OCC rules in §2.8 with write endpoint, `expected_enrollee_version` / `expected_physician_version`, error ID and 412.
- All 11 state machines / 51 transitions (47 distinct from→to pairs) covered with preconditions and side effects; 35 as explicit arrow pairs, the remaining 12 in prose (verified individually — e.g. panel-dimension `TRANSFER_PENDING`/`TRANSFERRED` moves, scorecard `→ SUPERSEDED`, distribution `PROPOSED → PAID`/`VOIDED`, the `RESERVED → RESERVED` re-estimate self-loop). Both `ACTIVE → TERMINATED` assignment variants (manual and system supersede) are distinguished.
- All 12 calculations covered with constants and rounding discipline; a scan of every numeric constant in each calculation found none missing except two figures from a single non-load-bearing worked example. Order-sensitive rules are stated as contractual: pinned per-member-then-sum rounding in reconciliation, the nested (floor-then-ceiling) PMPM clamp with 8000/95000, truncated pre-fee surplus ratio at waterfall step 5 with the explicit "post-fee re-tiering is forbidden" counterexample, single-rounding quality composite with 5000/2000/3000 weights and inclusive 8500/7000/5500 bands, largest-remainder allocation ordered `created_at` ASC then `npi` ASC.
- All 6 roles present, including the two `entity_backed` ownership roles.

**Hard Contract 3 — §3 Path Purity: PASS.** 281 distinct backticked tokens in §3; zero start with `/`, zero are bare HTTP methods, zero combine method+path. Endpoints in §3 are named only by state-transition, role+verb or capability framing.

**Coverage counts against scaffold:** 44/44 endpoints in the §4 table (exact method+path set match, no extras, all rows exactly 4 columns); 42/42 error codes in §5 with all HTTP statuses matching the scaffold, no extras, all rows exactly 2 columns; 12/12 entities; 12/12 calculations; 11/11 state machines.

**Style scan:** no fuzzy hedging words, no operator/pseudocode syntax (the only regex hits were the English word "return", including inside the verbatim §2.2 block). Two small text defects found during verification were fixed: an "approximately 1806.1578" hedge replaced with the exact nineteenths fraction, and a dropped word in the quality-band example sentence.

The two withheld design files (`SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`) were never opened, grepped, or referenced.

**Orchestrator truncation check (independent):** 426 lines; final section is `## 5. Error Code Catalogue`; endpoint table = 46 table lines (2 header + 44 rows) matching the 44 scaffold endpoints; error table = 42 `ERR_` rows. File ends on a complete table row at a real section boundary. NOT truncated — no regeneration needed.

## Step 5: Generate unit tests — 2026-09-02T18:51:46.707Z

Launched concurrently with Step 6 in a single assistant message, so `workspace/implementation/` did not exist when the test generator started and `test_suite/` did not exist when the implementation generator started (physical isolation both ways).

Queue A and queue B are both complete and verified.

## Files written

**Stage 1 — `.../test_helpers/` (9 files, complete and import-verified):** `__init__.py`, `types.py`, `constants.py`, `api_errors.py`, `api_client.py`, `test_users.py`, `factories.py`, `assertions.py`, `fixtures.py`. Untouched after Stage 2 began (mtimes predate all test-suite work).

**Stage 2 — `.../test_suite/`: `conftest.py` + 21 numbered modules**, 231 tagged test functions, **250 tests collected** (difference is `@pytest.mark.parametrize` expansion).

| queue | modules | instances | tagged tests |
|---|---|---|---|
| A (Difficulty §1.8) | `test_01`–`test_10` | 20 / 20, each ≥3 tests | 84 |
| B (Corner §1.9) | `test_11`–`test_21` | 54 / 55 non-stub | 147 |

Queue B modules: `test_11`/`test_12` entities (12 instances), `test_13`/`test_14` state_machines + consistency_model (11), `test_15`/`test_16` calculations (9), `test_17`/`test_18` validations (9), `test_19` endpoints (4), `test_20` errors + rbac (7), `test_21` cross_cutting_layers (3).

## Instance skipped (1, PRD-first filter)

`Corner/entities/create_physician_under_unknown_agreement_returns_not_found` — the instance asserts "priority 4 beats priority 3 for path ids" (404 `ERR_AGREEMENT_NOT_FOUND` for an unknown path agreement id whose body *also* omits required `full_name`). PRD §2.10 orders check **3 Request shape** (400 `ERR_INVALID_REQUEST`) *before* check **4 Path existence**, so for that exact request the PRD uniquely derives 400, contradicting the asserted outcome. No test, no placeholder, no skip marker emitted. All 31 `excluded_because:` stubs were left untranslated and every stub's `difficulty_instance` cross-reference was confirmed to resolve to a real depth-index instance.

## Verification performed

- **Design-citation pass:** every test carries exactly one `Design:` line; all 231 tags resolve to a real `name:` in the source yaml; no tag points at a stub.
- **PRD-citation pass:** every docstring quote greps verbatim against `PRD.md` after whitespace normalisation, is a complete rule-bearing sentence, and the cited `§X.Y` is the section the sentence actually lives in (0 problems). Sentences containing markdown `**bold**`/`*italic*` markers were avoided throughout, since they would break literal grep.
- **Coverage audit:** every difficulty instance ≥2 tests (actual range 3–6); every non-stub corner instance ≥1 test (actual 2–5); no tags outside the two indices.
- `pytest test_suite --collect-only` collects all 250 cleanly; no `skip`/`skipif`/`xfail`/mocking anywhere; the word "scaffold" appears in no comment or docstring.

## Notes worth passing on

- Three corner recipes specify `specialty: "FAMILY_MEDICINE"`, which is not one of the PRD's four specialties; `PRIMARY_CARE`/`INTERNAL_MEDICINE` was substituted (safe — the specialty gate only constrains `PEDIATRIC` and `SENIOR` members).
- All literal money/bps expectations were derived from the PRD's own worked examples and cross-checked with the reference arithmetic in `assertions.py` (e.g. the 86275 → 6039/80236/32094/48142 waterfall, the 3348 → 1806+1542 largest-remainder split, IBNR 3380 vs 1480, the 9500/9501 deficit boundary, attachment+1 recovery).
- Nothing under `workspace/implementation/` was read or written at any point, by me or by any of the four section subagents.

### Sub-agent detail (Step 5 corner queue: endpoints/errors/rbac) — retained for the record

Three design-index defects were corrected in favour of the PRD: (1) `specialty: "FAMILY_MEDICINE"` is not a PRD enum member (§3.2 allows PRIMARY_CARE, PEDIATRICS, INTERNAL_MEDICINE, OB_GYN) — used the PRIMARY_CARE default; (2) `measurement_period: "2026-H1"` violates §2.10 check 3 ("`measurement_period` is exactly four digits") — used `"2026"`; (3) one sub-assertion dropped — `stop_loss_recovery_links_pool_and_enrollee_with_snapshot_fields` asserts `stop_loss_eligible_enrollee_count == 1`, but with `stop_loss_attachment_cents` 1000 and PAID claims of 6000 and 3000, §3.6 derives 2, not 1; the instance is kept minus that one non-derivable number.

**Orchestrator verification:** `python3 -m pytest test_suite --collect-only -q` → `250 tests collected in 0.20s`.

## Step 6: Generate implementation — 2026-09-02T18:51:46.707Z

Implementation complete and verified.

## Files written (23, all under `workspace/implementation/`)

Top-level modules: `app.py`, `db.py`, `errors.py`, `response.py`, `middleware.py`, `validate.py`, `calc.py`, `derive.py`, `serialize.py`, `resolve.py`, `requirements.txt` (`flask>=3.0`), `start.sh` (executable).

Blueprints in `routes/`: `__init__.py`, `clock.py`, `agreements.py`, `physicians.py`, `enrollees.py`, `assignments.py`, `files.py`, `pools.py`, `claims.py`, `recoveries.py`, `quality.py`.

## Endpoints

**44 routes registered**, enumerated from the Flask URL map and matched one-for-one against the PRD §4 table (43 under `/ipa` plus `POST /_clock/set_current_utc`). All 12 entities, 42 error codes, 12 calculations, 11 state machines and 29 ordered validations are implemented.

## Boot confirmation

`bash start.sh` boots in the foreground (`exec python3 app.py`), honors `PORT` (default 10000), and logs `Running on all addresses (0.0.0.0)`. Storage is module-level dicts only — a scan for `sqlite3`, `open(`, `json.dump`, `pickle`, `shelve`, `/tmp` across the package returns nothing, and all 12 stores are empty on a fresh import (no seeding, no preloading).

## Verification

Two end-to-end smoke suites, each against a freshly launched server, both report **FAILURES: 0**:

1. Worked examples from the PRD: PMPM triples (37500/2625/34875, floored 8000/560, senior 89500); prorated expected capitation 86275 at 18387 member-month bps; variance −6194, withhold 6039, net payable 80236, professional 48142 / institutional 32094; accrual then exact reversal on dispute with sticky `WITHHELD` posture and panel closure; pool funding and `withheld_balance_cents` 6039 on posting; loss ratio 4154; IBNR 5000 (COMPLETION_FACTOR) then 7581 (PMPM_LOSS_RATIO self-loop); preview net claims 27581 / raw surplus 20561 / TIER_3; largest-remainder distributions exactly conserving both savings and withhold; settlement-window rejection then SETTLED draining the withhold to 0; settlement due dates 2027-06-29T23:59:59.000Z and 2027-09-27T23:59:59.000Z; and the auth/envelope/pagination contract (401/403/404/400/409/412/422 with correct `error_id`, exact `meta` key set).
2. Panel lifecycle: empty-store-at-boot assertion, auto-close at capacity, closed-panel and specialty gates, validation precedence (`ERR_ASSIGNMENT_BEFORE_COVERAGE` over overlap), the full transfer handshake including rejection (counts restored, panel resolves to `CLOSED_TO_NEW` never `OPEN`), the 4-level TRANSFERRED cascade with `PANEL_TRANSFER` successor and continuity stamp, `ERR_CONTINUITY_OF_CARE_ACTIVE` / `ERR_PANEL_NOT_TRANSFERRED` gates, exit cascade, and the supersede path with `superseded_by_assignment_id` back-pointer — with `total_assigned_members` conserved at every step.

One notable spec property worth flagging to whoever writes tests: `capitation_posture` is sticky at `WITHHELD` once any remittance of the agreement reaches `DISPUTED`, because disputed remittances are retained forever and the derivation quantifies over all of them. This is what the scaffold's `capitation_posture_derivation` specifies, so a later successful posting does not restore `CURRENT`.

## Step 7: Run tests and iterate — 2026-09-02T19:43:23.304Z

Clean sweep achieved.

## Summary

**Iterations run:** 4 full 8-round parallel sweeps.

**Final sweep (verified, `results.1..8.json` all written 19:36):**
```
round 1: 250/250   round 5: 250/250
round 2: 250/250   round 6: 250/250
round 3: 250/250   round 7: 250/250
round 4: 250/250   round 8: 250/250
```
0 failed, 0 errors, 0 skipped in every round.

**Tests deleted:** none. Every failure traced either to a PRD-faithful implementation defect or to a test/fixture mistranslation, so nothing had to be dropped for PRD silence.

**Fixes applied to `test_helpers/`:** none — the failing setups were per-test local helpers, not shared helpers.

**Fixes applied to `implementation/`** (all in `workspace/implementation/db.py`; no endpoint, field, side effect or capability added; storage still module-level dicts only):
- `add_days` — derived windows now inherit the source instant's precision, so `continuity_of_care_until` and `settlement_due_date` read `2026-05-30T00:00:00Z` / `2027-06-29T23:59:59Z` instead of gaining a fractional part the PRD never writes on business instants (PRD pins three fractional digits only for `created_at`/`api_request_timestamp`).
- new `fmt_instant_seconds` — whole-second renderer used by the above.
- new `audit_stamp()`, now used by `create()` and `touch()` instead of `real_now()` — PRD §2.5 forbids substituting the host wall clock, while §2.4 still pins three fractional digits, so audit fields read the logical clock and render normalised.

**Fixes applied to `test_suite/`** (4 files, no assertion weakened, no skip/xfail):
- `test_01_capitation_reconciliation_variants.py` — `test_withhold_is_rounded_once_on_the_expected_total`: the `6040` figure is 7% of the *prorated* per-member amounts, not the sum of the Enrollee `withhold_cents` fields (§3.3 uniquely derives 2625+6265+560 = 9450). Replaced with a difference assertion; the authoritative `6039` / `80236` checks are kept.
- `test_12_entity_resolution_and_defaults.py` — `_agreement_created_without_a_continuity_window` left the agreement in DRAFT, but §3.2 permits APPLICANT→CREDENTIALED only while the parent agreement is ACTIVE. Fixture now activates it.
- `test_16_reserve_preview_and_reparse_math.py` — `_build_mixed_match_file` discarded the credentialing response, so the "inactive physician" record was the stale APPLICANT payload. Fixture now keeps the post-credentialing record.
- `test_19_endpoint_contracts.py` — `test_the_proposal_persists_exactly_the_previewed_figures` compared `surplus_ratio_bps` against the persisted pool, but §3.7 declares that field only on the settlement-preview output (COMPUTED-FIELD SILENCE → STEP 1c split). The other five previewed figures are still compared.

**Environmental notes worth relaying:** two intermediate sweeps were destroyed by host contention rather than by defects — one round set was mass-SIGKILLed mid-collection at a single wall-clock instant (86–158 concurrent `prd-bench-local-run` processes on the box), and one round showed a lone bare `ConnectionResetError` in `test_08` that vanished on re-run. `results.*.json` is authoritative; grepping the shared `sweep.log` for `FAILED` is misleading because 8 runners interleave into one file.

**Orchestrator independent verification (per standing memory note that a Step 7 subagent can claim a clean sweep without artifacts):** 8 `results.*.json` files present on disk; re-parsed each with `json.load` — every round reports `passed=250 / total=250 / failed=0`. Confirmed, not taken on trust.

**Step 8 skip condition NOT met** (4 iterations, 4 `implementation/` fixes, 4 `test_suite/` fixes) → Step 8 runs.

## Step 8: Finalize PRD — 2026-09-02T19:54:06.239Z

`PRD_FINALIZED.md` is written. Six edits, all traced to `<step_7_diff>` items.

**Line counts:** PRD.md 426 → PRD_FINALIZED.md 428 (+2 lines, +0.47%). Prose delta is larger than the line delta because the file is long-line Markdown.

**Changes**

- §2.3 — revise — pinned that `created_at` comes from the logical clock so many resources share one value, and that ties wherever the document orders by `created_at` are resolved by server creation sequence (which also governs if the clock moved backwards) — `db.py:202` (`ordered`, sorts on `_seq`), `db.py:155` (`audit_stamp`)
- §2.4 — revise — `updated_at` rendered with three fractional digits and re-stamped on mutation; both audit stamps taken from the logical clock, never host wall clock, always rendered in normalised three-digit form regardless of the clock's literal text, so `updated_at` can repeat while `version` still advances — `db.py:155-189`
- §2.5 — insert — day-advanced derived instants (`continuity_of_care_until` on physician and on transfer successor, pool `settlement_due_date`) inherit the source instant's precision; whole seconds when the source carried no fractional part, else three digits, with the `2027-06-29T23:59:59Z` example — `db.py:100-112`, `db.py:30`
- §3.2 — revise — "twenty-ninth of May" → "thirtieth of May" (notice on 1 March + 90 days is 2026-05-30, which is what the implementation emits) — `routes/physicians.py:134`, `db.py:109`
- §3.5 — revise (two spots) — the 6040 figure is re-attributed to withholding each per-member prorated amount separately; the per-enrollee `withhold_cents` sum for that roster is stated as 9450; the "differ by cents" claim widened to "differ" — `calc.py:69` vs `calc.py:197`
- §3.7 — revise — `surplus_ratio_bps` and `admin_fee_bps` exist only on the settlement-preview output; not `RiskPool` fields, never persisted by the proposal, absent from a pool's representation — `calc.py:281`, `serialize.py:61-69`, `routes/pools.py:144-148`

**No edit made for** the `test_12` (agreement left in DRAFT) and `test_16` (stale APPLICANT payload) fixture fixes — §3.2 and §3.5 already determine both behaviours uniquely; those were pure fixture bugs.

**Per-edit pre-edit search log**

1. §2.3 ordering. (a) Subject: meaning of "ordered by `created_at` ascending" once audit stamps read a frozen logical clock. (b) Enumerated: `db.ordered` and every reverse-reachability helper in `db.py:210-255`; all six direct `db.ordered(...)` list routes (`assignments.py:150`, `enrollees.py:75`, `agreements.py:95`, `claims.py:93`, `pools.py:295`, `recoveries.py:78`); the roster walk `calc.py:162` and its intra-enrollee `sorted` on `(effective_date, _seq)` at `calc.py:188`; participant ordering `pools.py:132` (`(_seq, npi)`); largest-remainder tie-break `calc.py:322-326` (index order); `derive.sync_enrollee_assignment` `active[-1]`; `pools._participants` last-FINAL-wins scorecard pick. All are `_seq`/insertion order. (c) Wording adjusted twice: dropped an "orders **or selects** by created_at" phrasing because §3.2's `quality_composite_bps` selection is not implemented as a created_at-descending scan (`quality.py:131` assigns at finalisation), and made the rule a direction-neutral *tie-break* rather than "returned in creation order" so descending orderings elsewhere are not mis-described.
2. §2.4 audit stamps. (a) Subject: source and rendering of `created_at`/`updated_at`. (b) Enumerated: only writers are `db.create:169/171` and `db.touch:189`, both via `audit_stamp()`; `fmt_instant` vs `fmt_instant_seconds`; `real_now()` remaining callsite `response.py:16`; `serialize._render`; `ROW_FIELDS` (row has `created_at` only, also from `audit_stamp`). (c) Scoped the sentence to "both audit stamps" so it cannot be read as covering `api_request_timestamp`, which still uses host time per `response.py:16`; added the "same instant while the clock stands still / `version` still advances" clause so "refreshed on every mutation" is not read as requiring a changed value.
3. §2.5 derived instants. (a) Subject: rendering precision of server-derived instants. (b) Enumerated all three `add_days` callsites (`physicians.py:134`, `assignments.py:280`, `pools.py:53`) plus every other instant field to make sure none is misdescribed: `received_at` (`files.py:59`), `received_date` (`claims.py:73`), `exit_notice_at` (`physicians.py:131`), `term_date` (`assignments.py:310` and `:266`), caller-supplied `effective_date`/`service_date`/`coverage_*`/`pool_year_*`, and the clock echo at `clock.py:19`; `Instant.render`/`raw` semantics in `db.py:38-58`. (c) Restricted the sentence to instants "derived by advancing another instant by a whole number of days" and enumerated the three fields by name, so the pre-existing verbatim-echo behaviour of caller-supplied instants is neither asserted nor contradicted; the successor-assignment window was added to the field list (Step 7 named only two, but `assignments.py:280` is the same code path).
4. §3.2 date arithmetic. (a) Subject: `exit_notice_at + continuity_of_care_days`. (b) Enumerated `physicians.py:131-135`, `assignments.py:279-281`, `db.add_days:109`, and the consuming gate `assignments.py:307` (check 14). Plain calendar-day addition everywhere; 2026-03-01 + 90 = 2026-05-30. (c) None — single word changed, no scope question.
5. §3.5 withhold example. (a) Subject: which quantities are *not* the remittance withhold. (b) Enumerated `calc.member_pmpm_components:69` (per-enrollee withhold on clamped gross), `calc.remittance_variance_and_allocation:197` (single withhold on the expected total), `calc.expected_capitation_for_coverage_month:180-186` (per-member amounts rounded then summed), and §3.3's own worked figures for the §3.5 roster (37500/89500/8000 → 2625/6265/560). (c) Kept both wrong answers explicitly labelled wrong and left 6039 as the sole authoritative figure, so no implementer can read the added 9450 as a computed field; also widened "differ by cents" to "differ" since 6039 vs 9450 is not a cents-level gap.
6. §3.7 preview-only fields. (a) Subject: where `surplus_ratio_bps`/`admin_fee_bps` live. (b) Enumerated `calc.pool_settlement_waterfall:252-286` (the only producer), `pools.settlement_preview:101-113`, `pools._propose_settlement:143-148` (persists only raw surplus, tier, admin fee cents, distributable, shared savings), `pools._void_settlement:191-195` (resets the same five), `serialize.POOL_FIELDS:61-69` (neither field present), and PRD §3.7's pool-creation zero list. (c) Widened from `surplus_ratio_bps` alone to include `admin_fee_bps`, since the implementation treats both identically; had I named only the former, the PRD would have left `admin_fee_bps` looking like a pool field.

**Orchestrator verification:** `PRD_FINALIZED.md` present, 428 lines, ends on the complete final error-table row (no truncation).

## Step 9: Complete PRD — 2026-09-02T20:14:38.832Z

`PRD_COMPLETED.md` is complete.

## Verification
- Ends at a real section boundary: last line is `| \`ERR_ALLOWED_EXCEEDS_BILLED\` | 422 Unprocessable Entity |`, the final row of the §5 error-code table. Not truncated.
- `diff` of all `^#` heading lines against the source is empty — no sections added, removed or reordered.
- All 44 route decorators in `implementation/routes/` match the §4 endpoint table exactly (method + path), verified by set diff.

## Line counts / char delta
| file | lines | chars |
|---|---|---|
| `workspace/PRD_FINALIZED.md` | 428 | 110,985 |
| `workspace/PRD_COMPLETED.md` | 428 | 123,710 |

Char delta **+12,725**. Line count unchanged at 428 (≥ 428 as required) because every change is an in-paragraph insert or revision; no new paragraphs.

## Counts
- **ambiguity-pins: 25**
- **mismatch-revisions: 10**

## Changes
- §2.2 — insert — ambiguity — `api_request_id` is `req_` plus exactly 20 chars from uppercase Latin letters and digits — `implementation/response.py:15`
- §2.2 — insert — ambiguity — `api_request_timestamp` is the one instant read from the host's real wall clock, not the logical clock — `implementation/response.py:16`
- §2.3 — insert — ambiguity — non-integer `limit`/`offset` text, out-of-enum filter values and empty filter values all give `ERR_INVALID_REQUEST`; an id filter matching nothing gives an empty page — `implementation/validate.py:152,161,189`
- §2.4 — insert — ambiguity — three-way instant rendering (caller-supplied echoed verbatim; server-stamped business fields in the clock's literal text; only `created_at`/`updated_at` normalised) and `version`/`updated_at` move at most once per resource per request — `implementation/db.py:52,155,178`
- §2.5 — revise — mismatch — clock response `data` is `{"current_utc": ...}` echoing the literal text supplied; no ownership check on the clock endpoint — `implementation/routes/clock.py:19`
- §2.10 check 1 — insert — ambiguity — a whitespace-only auth header counts as empty — `implementation/middleware.py:23`
- §2.10 check 2 — insert — ambiguity — per-move role refinement keyed on `to_state`/`panel_status`/arrow, evaluated after checks 3 and 4 — `implementation/middleware.py:38`
- §2.10 check 6 — revise — mismatch — enumerated the field compared on each single-resource read, and exempted the six top-level collection listings plus the clock endpoint from ownership entirely — `implementation/middleware.py:44`
- §3.1 — insert — ambiguity — both IBNR parameters required on every create whatever `ibnr_method` is chosen; `continuity_of_care_days` optional, ≥ 0, default 90; all other named fields required — `implementation/routes/agreements.py:37-53`
- §3.1 — insert — ambiguity — `SUSPENDED → ACTIVE` neither resets `capitation_posture` nor re-derives enrollee components; `DRAFT → ACTIVE` bumps an enrollee's `version` only when a component value actually changes — `implementation/routes/agreements.py:132-134`, `implementation/derive.py:139`
- §3.2 — insert — ambiguity — credential endpoint takes one `to_state` over all five states; per-arrow actor split; `APPLICANT` parses then fails `ERR_INVALID_STATE_TRANSITION` — `implementation/routes/physicians.py:20,104`
- §3.2 — insert — ambiguity — panel endpoint's field is `panel_status`, admits all four states, `TRANSFER_PENDING`/`TRANSFERRED` refused; reopen is `NetworkManager`-only; check 11 outranks check 29 on reopen — `implementation/routes/physicians.py:28,162,170-178`
- §3.2 — revise — mismatch — `quality_composite_bps` is written directly by whichever scorecard was finalised last **in time**, never re-derived from the surviving `FINAL` set and never walked back — `implementation/routes/quality.py:131`
- §3.4 — insert — ambiguity — `PANEL_TRANSFER` is a sendable `assignment_reason`; `supersede_prior` defaults to false when omitted — `implementation/routes/assignments.py:58`
- §3.4 — insert — ambiguity — an overlapping non-terminal row that fails either supersede condition is refused `ERR_ASSIGNMENT_PERIOD_OVERLAP` — `implementation/routes/assignments.py:98-102`
- §3.4 — insert — ambiguity — `to_physician_id` and `transfer_effective_date` required on the proposal only, and `transfer_effective_date` is not a response field — `implementation/routes/assignments.py:220`
- §3.4 — insert — ambiguity — answering a transfer is `PhysicianUser`-only; propose/complete/terminate are `NetworkManager`-only — `implementation/routes/assignments.py:21,190`
- §3.4 — insert — ambiguity — successor created with `pending_to_physician_id`/`term_date`/`superseded_by_assignment_id` null; the completion call returns the **predecessor** — `implementation/routes/assignments.py:282`
- §3.5 — insert — ambiguity — appending a row to a file not in `RECEIVED` is `ERR_INVALID_STATE_TRANSITION` (409) — `implementation/routes/files.py:115`
- §3.5 — insert — ambiguity — the net retroactive figure is file-internal; a file exposes only four counters, and the figure surfaces later as the remittance's `retro_adjustment_cents` — `implementation/routes/files.py:65,252,262`
- §3.5 — insert — ambiguity — covered days are tested at each day's midnight-UTC instant; each member's whole member-month is attributed to the earliest-starting qualifying assignment, ties by creation sequence — `implementation/calc.py:174-175,188`
- §3.5 — insert — ambiguity — file `dispute_reason` is required on that transition and retained rather than echoed — `implementation/routes/files.py:195,294`
- §3.5 — revise — mismatch — resubmission also resets `claimed_capitation_cents` and the retained retro figure, and leaves `row_count` untouched — `implementation/routes/files.py:309-312`
- §3.5 — insert — ambiguity — posting under a non-`ACTIVE` agreement is `ERR_INVALID_STATE_TRANSITION`, not `ERR_AGREEMENT_NOT_ACTIVE` — `implementation/routes/files.py:230-231`
- §3.6 — revise — mismatch — `billed_cents` must be zero or more, not at least 1 — `implementation/routes/claims.py:43`
- §3.6 — revise — mismatch — claim `denial_reason` is a required free-form non-empty string, not enum-validated — `implementation/routes/claims.py:131`
- §3.7 — insert — ambiguity — pool create imposes no relative order on `pool_year_start`/`pool_year_end`; an inverted period is accepted — `implementation/routes/pools.py:29-44`
- §3.7 — insert — ambiguity — recovery create checks neither the pool's nor the agreement's `status`; the pool-status restriction bites only at approval — `implementation/routes/recoveries.py:33-52`
- §3.7 — revise — mismatch — recovery `denial_reason` is a required free-form non-empty string, not enum-validated; plus the list filters and read fields — `implementation/routes/recoveries.py:106,73-75`, `implementation/serialize.py:78-83`
- §3.7 — revise — mismatch — `ibnr_method_override` on the preview is a **query** parameter, and when omitted the preview reuses the pool's stored `ibnr_reserve_cents` rather than recomputing under the agreement default — `implementation/routes/pools.py:104,109-113`
- §3.8 — insert — ambiguity — `FINAL` is the only actionable `to_state`; wrong `to_state`, non-`DRAFT` scorecard and out-of-scope credential all yield `ERR_INVALID_STATE_TRANSITION` — `implementation/routes/quality.py:110-116`
- §3.8 — insert — ambiguity — an empty participant set still proposes: waterfall written, pool reaches `SETTLEMENT_PROPOSED`, zero distributions created — `implementation/routes/pools.py:150-151`
- §3.8 — revise — mismatch — `composite_score_bps_snapshot` is read off the qualifying `FINAL` scorecard, not the physician's `quality_composite_bps` — `implementation/routes/pools.py:175`
- §3.8 — insert — ambiguity — largest-remainder allocation returns all zeros when the total is 0 or the weights sum to 0 — `implementation/calc.py:314-315`
- §3.8 — revise — mismatch — pool `dispute_reason` is **optional** (unlike the file dispute) and not echoed; `SETTLEMENT_PROPOSED → RESERVED` is `PayerRepresentative`-only while every other pool arrow is `IpaAdmin`-only — `implementation/routes/pools.py:221,227-231`

Two impl behaviours were deliberately left unpinned as out-of-contract: the `HTTPException` fallbacks in `implementation/app.py:45-55` (`ERR_NOT_FOUND`/`ERR_METHOD_NOT_ALLOWED`/`ERR_INVALID_REQUEST`/`ERR_INTERNAL` for unrouted paths and bad methods) are not endpoint contracts and adding them would have meant new rows in the §5 table.

**Orchestrator verification:** `workspace/PRD_COMPLETED.md` present — 428 lines, 123,710 chars, final heading `## 5. Error Code Catalogue`, last line is the complete `ERR_ALLOWED_EXCEEDS_BILLED` table row. Not truncated. **Pipeline complete through Step 9.**
