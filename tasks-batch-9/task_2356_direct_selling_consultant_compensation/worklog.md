# Worklog — task_2356_direct_selling_consultant_compensation

## Step 1: Create task directory — 2026-09-02T05:40:00.000Z

Created `tasks/task_2356_direct_selling_consultant_compensation/` and `workspace/` subdirectory (name pre-allocated by the caller; no index scan performed).

## Step 2: Generate scaffold — 2026-09-02T06:03:00.000Z

Scaffold complete for scenario 2356. All three files are written and the lint is clean.

## Lint verdict (verbatim)

```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           tasks/task_2356_direct_selling_consultant_compensation/SCAFFOLD.yaml
  Difficulty design:  tasks/task_2356_direct_selling_consultant_compensation/SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      tasks/task_2356_direct_selling_consultant_compensation/SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    65
  §1.1 entities declared:     13
  §1.8 instances scanned:     21
  §1.9 instances scanned:     51
  Calls scanned (§1.8+§1.9):  1482

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

## Artifacts

- `SCAFFOLD.yaml` (§1.0–§1.7)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (§1.8 only)
- `SCAFFOLD_CORNER_DESIGN.yaml` (§1.9 only)

## Counts

- 13 entities, 9 state machines, 2 concurrency rules, 10 calculations, 69 ordered validations, 65 endpoints, 91 error codes, 7 roles.
- complexity_profile: entity_topology `graph`, state_machine_shape `parallel`, role_model `segregation_of_duties`, consistency_model `immediate`, layers `dual_variant_calculation`, `cascading_side_effects`, `derived_field_reconciliation`, `optimistic_concurrency`.
- §1.8: 21 instances across the nine difficulty rules (2–3 each).
- §1.9: 73 instances in 9 sections — entities 12, state_machines 22, calculations 13, validations 8, endpoints 5, errors 4, rbac 3, cross-cutting layers 5, consistency model 1. Of those, 51 carry a full `test_recipe` and 22 are `excluded_because` stubs, each naming an existing §1.8 instance.

## Coverage audit

- All 91 error codes are triggerable across §1.8 + §1.9 (verified programmatically; zero uncovered, zero invented codes).
- Both `concurrency_rules` entries have their own OCC stale-version instance using the declared `write_endpoint`/`occ_field` (`stale-period-version-on-run-create` → 412 `ERR_STALE_PERIOD_VERSION`; `stale-run-version-on-disclosure-draft` → 412 `ERR_STALE_RUN_VERSION`, where drafting a disclosure itself consumes the run version).
- Every §1.9 `section:`/`claim_type:` value comes from `references/claim-extraction-guide.md`; topology (`graph`), shape (`parallel`, `compound`, `cyclic`, guarded), side-effect patterns (cascade down, cross-entity, conditional cascade, ledger sync, compensation), dual-variant rows and the consistency row are all represented, the redundant ones as stubs.
- Difficulty knobs (harder-than-expert): dual compression variants (DYNAMIC vs STATIC with forfeiture), per-line tax rounding vs aggregate basis, marginal PV bands then rank bump then cap then probation haircut in a pinned order, withholding capped by clawback balance, buyback restocking fee tiered on the gross refund (returning one more unit nets 540 cents less), floor-only sell-through ratio, half-open period intervals vs closed sanction intervals with a cool-off buffer, and a five-level refund cascade ending at a published disclosure.
- Structural checks: instance names unique across both design files, no stub carries a `test_recipe`, every cited `difficulty_instance` resolves, all `${var}` placeholders bound by an earlier capture, `expected_*_version` always a captured variable, and `SCAFFOLD.yaml` contains neither design key.
- No sibling task directory was read, listed, or grepped at any point.

## Step 3: Copy shared files — 2026-09-02T06:03:00.000Z

Copied `INSTRUCTION.md` from project root to `workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-09-02T06:20:00.000Z

PRD generated and verified.

## Output
`workspace/PRD.md` — **507 lines**

## Sections written
- **§1 Introduction** — pain-first framing (spreadsheet-run compensation cycle that can't be replayed), scope of the arc from enrollment to income disclosure, and the two design commitments (integer arithmetic, attributability).
- **§2 Global Specifications** — 11 subsections: 2.1 Actors/Headers/RBAC (7 roles, `X-User-ID` + `X-User-Role`, both `identity:` bindings translated to prose, full segregation-of-duties role map incl. `PlatformAdmin`'s exclusion from the money path and from `accept-agreement`); 2.2 API Response Structure (byte-verbatim paste, diff-verified); 2.3 Pagination and List Ordering (10/1/100/0 + the three ordering overrides + `created_at` tie-break); 2.4 Common Resource Properties (incl. the explicit `TaxJurisdiction` exception — only `id` and `created_at`); 2.5 The Logical Clock; 2.6 Money/Volume/Basis Points (round-half-up default, rounding position is normative, the single floor exception); 2.7 Version Preconditions (both OCC rules, 412, version increment on success); 2.8 Order of Rejection (8-step shared prefix + the three declared priority pairs); 2.9 Not-Found catalogue (all 13 path/body reference → 404 mappings); 2.10 Genealogy Integrity and Cascading Recomputation; 2.11 Segregation of Duties.
- **§3 Business Logic** — 9 subsections (config/tax/catalogue; enrollment's 3 gates + compound status; ordering with per-line tax and the seventy-percent rule; qualification cycle; commission runs; buybacks; compliance ladder; termination/reinstatement/rank override; income disclosure). All 10 calculations rendered as ordered prose steps, both dual-variant calculations (`DYNAMIC`/`STATIC` compression, `ALL_ENROLLED`/`PAID_ONLY`) given symmetric treatment, and each operation's domain-check ordering stated inline.
- **§4 Endpoint Definitions** — 65 rows, exactly 4 columns.
- **§5 Error Handling** — 91 rows, exactly 2 columns. Document ends here; no audit footer.

## Hard Contract audit
- **Contract 1 (Field-Name Coverage): PASS** — 246-name target set (227 entity fields + endpoint inputs + path params + 31 nested-array member names) checked against backticked tokens in the PRD; **0 missing**, confirmed on two independent passes. Additionally: all field `enum` values → 0 missing; all state-machine state names → 0 missing; all 91 `errors[].id` appear in §2/§3 prose (not only in the §5 table).
- **Contract 2 (Rule Coverage): PASS** — validation priority: all three declared priority pairs stated explicitly with the losing error named (12>16, 27>33, 46>48), plus per-endpoint orderings for all 40 multi-check operations. OCC: both `concurrency_rules` in §2.7 with field, comparison, 412 error, no-write-on-failure, and version increment. Cross-entity side effects: every endpoint `side_effects` entry traced (approve→sponsor/plan counters; pay→volume + ancestor recompute; lock→row materialisation + sanction expiry; close→tenure/activity flips; run pay/reverse→consultant ledgers; buyback refund→5-branch cascade incl. `correction_pending`/`correction_flagged`/`PERIOD_CORRECTION`; case decision→status + sanction ladder; publish→`NEWER_PUBLICATION` supersession). `applies_to` scopes: every multi-endpoint validation restated at each site — verified programmatically (`ERR_APPLICATION_TERMINAL` 6 sites, `ERR_APPLICATION_NOT_DRAFT` 4, `ERR_CONSULTANT_NOT_ORDER_ELIGIBLE` 3 with the terminated-consultant asymmetry, `ERR_PERIOD_NOT_ACCEPTING_VOLUME` 3, `ERR_RUN_NOT_PAID` 3, `ERR_SEGREGATION_OF_DUTIES` 2, `ERR_APPROVED_RUN_BLOCKS_TERMINATION` 2, `ERR_CONSULTANT_ALREADY_TERMINATED` 2, `ERR_SPONSOR_NOT_ELIGIBLE` 2). Structured field content: `pv_bonus_bands`, `rank_ladder` (all 4 rungs with every threshold and override rate), `lines[]`, `override_breakdown`, `distribution_buckets` all rendered member-by-member. Sibling symmetry: all 8 branch pairs given both branches, including `REJECT`'s exemption from the suspended-earner block and `DENY`'s reason requirement.
- **Contract 3 (§3 Path Purity): PASS** — 0 `/`-prefixed backtick tokens, 0 bare HTTP methods, 0 method+path combos, and 0 raw `/direct-selling…` strings anywhere in §3; all operations are named by state transition, role+verb, or capability.
- **Fidelity sweep** — no pseudocode operators (`>=`, `+=`, `min()`, `ceil()`, `AND`, `IN`) leaked into prose; one hedge ("about six months") found and removed so `reinstatement_window_days` reads as exactly 180 days.

Constraint respected: neither `SCAFFOLD_DIFFICULTY_DESIGN.yaml` nor `SCAFFOLD_CORNER_DESIGN.yaml` was opened, grepped or referenced, and no sibling task directory was read.

## Step 5: Generate unit tests — 2026-09-02T08:00:00.000Z

Generation is complete. All 13 test files plus the helper package are written, compile clean, and pass every audit.

## Files written

**`test_helpers/`** (Stage 1, 8 modules + `__init__.py`): `api_client.py` (one method per §4 endpoint, prefix `/direct-selling`), `api_errors.py`, `types.py`, `constants.py`, `factories.py`, `fixtures.py` (tiered scenario builders, all preconditions built through PRD endpoints), `assertions.py`, `test_users.py` (seven roles; entity-backed `Consultant`/`Applicant` builders plus `make_headers` for segregation tests).

**`test_suite/`**: `conftest.py` + `test_01` … `test_13`:
| file | A | B | tot |
|---|---|---|---|
| 01 configuration_and_catalogue | 0 | 15 | 15 |
| 02 enrollment_gates | 2 | 6 | 8 |
| 03 order_pricing_and_tax | 2 | 3 | 5 |
| 04 order_lifecycle_and_time_windows | 4 | 2 | 6 |
| 05 sell_through_and_inventory_loading | 4 | 1 | 5 |
| 06 qualification_cycle_and_rank_tenure | 2 | 5 | 7 |
| 07 commission_earnings_and_compression | 4 | 5 | 9 |
| 08 run_approval_payout_and_holds | 6 | 3 | 9 |
| 09 buybacks_volume_reversal_and_clawback | 6 | 2 | 8 |
| 10 compliance_cases_and_sanction_windows | 6 | 1 | 7 |
| 11 termination_reassignment_and_reinstatement | 4 | 2 | 6 |
| 12 income_disclosure_and_read_after_write | 2 | 3 | 5 |
| 13 access_control_and_segregation | 0 | 5 | 5 |
| **total** | **42** | **53** | **95** |

## Coverage audit (machine-checked against both design yamls)
- Difficulty (queue A): **21/21 instances covered, every one by ≥2 tests** (42 tests).
- Corner (queue B): **51/51 non-stub instances covered by ≥1 test** (53 tests); the 22 stub instances (no `test_recipe`) were not translated, as specified.
- `Design:` tags: exactly one per test, always the docstring's last line, every `rule_id`/`section` and instance name resolving to a real yaml entry — 0 problems.
- Queue ordering: A-tests precede B-tests in every file (test_02 was reordered to comply).
- Citations: 100 quoted `PRD: "…"` excerpts are exact whitespace-normalised substrings of `workspace/PRD.md`; test_01's docstrings quote PRD prose unquoted and were verified verbatim sentence-by-sentence (all FULL-OK/PARTS n/n).
- No `skip`/`skipif`/`xfail` anywhere (the only `pytest.mark` use is a `parametrize` in test_01); no comment mentions "scaffold"; `py_compile` clean for all 22 modules.

## Instances skipped / deliberate deviations
- No non-stub instance was skipped.
- Three recipe assertions contradicted the PRD and were resolved in the PRD's favour: `rank_source` asserted as `ADMIN_ADJUSTED` (PRD L317, recipe said `ADJUSTMENT`); `termination_reason` `DISCIPLINARY` used instead of the recipe's non-enum `COMPLIANCE`; and the reinstatement-sponsor claim ("nearest live ancestor") was replaced by a scenario the PRD uniquely derives (reinstated consultant's `reassigned_from` ancestor is terminated with no live ancestor ⇒ sponsor `null`), with the ambiguous case left unasserted.
- `Corner/consistency model/every_side_effect_of_a_write_is_readable_in_the_next_request` has no "consistency model" prose in the PRD; it was grounded on the termination-cascade sentences (L311), which uniquely derive every asserted value.

Scope constraints were respected: `workspace/implementation/` was never read, and no sibling task directory was accessed.

## Step 6: Generate implementation — 2026-09-02T07:52:00.000Z

Implementation complete and verified.

## Files written
All under `workspace/implementation/` (~4,130 lines):

- `start.sh` — `set -euo pipefail`, `cd "$(dirname "$0")"`, guarded `pip install` (only when flask is missing, so per-test reboots are fast), `exec python3 app.py`; binds `0.0.0.0:$PORT` (default 10000) in the foreground
- `requirements.txt`, `app.py` (blueprints under `/direct-selling`, `ApiError` + 404/405/400/500 handlers all in the standard envelope)
- Core: `db.py` (empty in-memory store, no seeding), `common.py` (exact-integer half-away-from-zero `rhu`, `trunc_div`, clock, validators, pagination), `errors.py` (all 91 error IDs), `response.py` (meta/envelope), `middleware.py` (`X-User-ID` + `X-User-Role`, ownership)
- `services/`: `planlib.py`, `genealogy.py`, `qual.py`, `commission.py`, `disclosure.py`, `consultant_ops.py`, `lookup.py`
- `routes/`: `config.py`, `enrollment.py`, `consultants.py`, `orders.py`, `periods.py`, `runs.py`, `buybacks.py`, `compliance.py`, `disclosures.py`

## Verification
- **65/65 endpoints** implemented — programmatic diff of the PRD §4 table against `app.url_map` shows zero missing, zero extra.
- **91/91 error IDs** present with HTTP statuses matching PRD §5 exactly (programmatic diff).
- Five smoke batteries against a fresh `bash start.sh` boot confirmed, among others: full enrollment→consultant mint; genealogy depth/path/reassignment; per-line tax and shipping; sell-through 476 bp and the 70 % rule; PV-bonus banding + senior bump (500 pts → 3,500 c); DYNAMIC compression (B paid_level 1 = 9,600 c, C paid_level 2 = 4,800 c) vs STATIC on identical volume (4,800 + 2,400, forfeited 800 c) with `distributable_pool = gross + forfeited`; REJECT→recalculate leaving `calculation_sequence` 0 then 1 on the two generations; withholding tiers (1,000 bp at 14,000 c, 2,500 bp at 33,100 c) capped at the clawback balance; payout-hold snapshot forcing full carry-forward; reversal → clawback + `RUN_REVERSED` supersede; buyback five-step settlement and the full refund cascade (order `RETURNED_PARTIAL`, `correction_pending`, `correction_flagged`, `PERIOD_CORRECTION`); rank tenure across four closed periods (advance after 2 consecutive, demote when grace 2 > 1); suspension expiry at lock; disclosure metrics (median/p90/decile/buckets hand-checked) and the whole DRAFT→LEGAL_REVIEW→revision→publish→`NEWER_PUBLICATION` chain. Fresh boot lists all 13 collections with `total_count: 0`.

## Ambiguities resolved
- **`X-User-Role` vs SCAFFOLD's `X-Role`** — PRD §2.1 wins; only `X-User-ID`/`X-User-Role` are read.
- **Volume posted to `personal_volume_points`** — `total_volume_points` (not commissionable), per SCAFFOLD's field description; `retail_/inventory_volume_points` are the `order_type` splits.
- **Statement `calculation_sequence`** — records the **pre-increment** run value (0 on first calculate, run ends at 1), per "at the moment it was produced" plus the transition's listed side-effect order.
- **Rounding** — implemented as exact integer arithmetic (equivalent to `Decimal` + `ROUND_HALF_UP` at unlimited precision), never float; the only truncation is `sell_through_bp`.
- **Seventy-percent rule reference row** — only the single most recent CLOSED period is consulted; no row ⇒ admitted unconditionally.
- **Sanction window conflict** — compared against other cases of the same consultant whose status is `SANCTIONED` (SCAFFOLD's literal wording), overlap of closed intervals plus the cooling-off buffer.
- **`refunded_cents`** — recomputed as the cumulative `net_refund_cents` of all REFUNDED buybacks referencing that order (idempotent).
- **Datetimes** — `created_at`/`updated_at` and computed instants use canonical 3-fractional-digit ISO; logical-clock stamps echo the clock string verbatim; client-supplied datetimes are stored verbatim.
- **Required vs optional** — fields the PRD phrases as "takes a X" (`reason`, `reversal_reason`, `rank_code`, `appeal_statement`, `agreement_version`, `identity_document_reference`) are treated as required.
- Derived-field recomputation bumps `updated_at`/`version` only when a value actually changes; `TaxJurisdiction` carries only `id` + `created_at`.

## Step 7: Run tests and iterate — 2026-09-02T13:04:00.000Z

Note (orchestrator, resume run): a prior Step 7 attempt on this task launched its 8-round sweep WITHOUT `setsid`, so all 8 rounds were SIGTERM-reaped mid-flight (`.sweep/round_*.log` stop mid-file at 11:30–11:33 UTC, no `.sweep/DONE`, no `results.*.json` produced). Those logs' ERRORs are reaping artifacts, not test failures. Stale `results.*.json` (none present) and `__pycache__` trees were removed and the sweep was re-launched under `setsid nohup`.

Subagent summary (verbatim):

**Iterations run:** 1 (one full 8-round parallel sweep; no fixes were needed).

The prior sweep logs in `.sweep/` were stale reaping artifacts, as flagged. I launched a fresh sweep under `setsid nohup` (`/home/ubuntu/github/CodingPRD/tasks/task_2356_direct_selling_consultant_compensation/.sweep/run.sh`), polled to `DONE` (~22 min wall clock per round, run concurrently), and read all 8 results files.

**Final sweep — per-round passed/total:**

| Round | Result |
| --- | --- |
| 1 | 107 / 107 |
| 2 | 107 / 107 |
| 3 | 107 / 107 |
| 4 | 107 / 107 |
| 5 | 107 / 107 |
| 6 | 107 / 107 |
| 7 | 107 / 107 |
| 8 | 107 / 107 |

failed = 0, errors = 0, skipped = 0 in every round. (95 test functions in `test_suite/` expand to 107 parametrized cases — the 12 extra come from `test_not_found_errors_for_every_entity_path`.)

**Tests deleted:** none — no test failed in any round, so no STEP 1 coverage/derivability adjudication was triggered.

**Fixes applied to `test_helpers/`:** none.

**Fixes applied to `test_suite/`:** none.

**Fixes applied to `implementation/`:** none.

**Contract sanity checks I did run (all clean):**
- No `pytest.mark.skip` / `xfail` anywhere in `test_suite/` or `test_helpers/` — the green sweep is not masked by suppressed tests (the grep hits were prose in docstrings about "skipped" compression levels).
- `workspace/implementation/db.py` `Store.__init__` constructs only empty dicts plus the PRD §2.5 clock default `2026-08-01T00:00:00Z` — no seeded/preloaded entities.
- Storage is in-memory only: no sqlite, no file writes, no `/tmp` cache, no JSON dumps anywhere in `implementation/`, so `start.sh` re-invocation under `--isolation per-test-server` wipes all state (which the sweep exercises 107 times per round).

No further action required — the artifact is stable across 8 concurrent rounds on a loaded host.

Orchestrator verification: re-read all 8 `workspace/implementation/results.{1..8}.json` independently — every round reports `total=107, passed=107, failed=0, errors=0, skipped=0`. Step 7 complete.

## Step 8: Finalize PRD — SKIPPED — 2026-09-02T13:05:00.000Z

Skip condition met: Step 7 exited on the first 8-round sweep with 0 test deletions, 0 `test_suite/` fixes, 0 `test_helpers/` fixes, and 0 `implementation/` fixes — zero iterations beyond the baseline. `PRD.md` therefore already determined every behavior the tests exercised, and there is no `<step_7_diff>` to patch against. `PRD_FINALIZED.md` is intentionally not produced; Step 9 starts from `PRD.md`.

## Step 9: Complete PRD — eliminate residual ambiguity and mismatch — 2026-09-02T13:20:00.000Z

Subagent summary (verbatim):

PRD_COMPLETED.md is written.

**Counts** — source `PRD.md`: 507 lines / 114,222 chars. `PRD_COMPLETED.md`: 507 lines / 121,706 chars (**+7,484 chars, 0 line-count change**, 28 lines touched, no new sections/paragraphs/renumbering). 33 pins total: **30 ambiguity-pins, 3 mismatch-revisions**.

**Changes**

- §2.1 RBAC — insert — ambiguity — absent/empty/whitespace-only auth header is `ERR_UNAUTHENTICATED` before body parsing — `implementation/middleware.py:28`
- §2.1 RBAC — insert — ambiguity — row ownership runs before body validation; list endpoints apply no owner scoping, so `Consultant`/`Applicant` callers see every matching row — `implementation/middleware.py:50`
- §2.3 Pagination — insert — ambiguity — `limit` outside 1..100, negative `offset`, or non-integer literal is `ERR_VALIDATION`; filters are exact-match, conjunctive, enum filters validated (undeclared member `ERR_VALIDATION`), id/code filters just match nothing — `implementation/common.py:239`
- §2.3 Ordering — revise — mismatch — the order tie-break on `merchandise_subtotal_cents` applies to any `created_at` tie, not only same-consultant/same-period orders; insertion order is the final tie-break; `meta` carries `limit`/`offset`/`total_count`/`has_more` with `has_more = offset + returned < total_count` — `implementation/routes/orders.py:51`, `implementation/response.py:49`
- §2.5 Clock — insert — ambiguity — clock read/write both answer with an object whose only member is `current_utc`; submitted value stored/echoed verbatim — `implementation/routes/config.py:43`
- §2.5 Clock — revise — mismatch — logical-clock stamps are verbatim copies of the clock's current spelling, but `created_at`/`updated_at` read wall-clock time — `implementation/db.py:23`
- §2.8 rule 3 — insert — ambiguity — a path id resolving to no row falls through to step 5's 404, while body `consultant_id` on the two creation endpoints is compared as a raw string, so a foreign or nonexistent value is `ERR_FORBIDDEN_RESOURCE` before validation — `implementation/routes/orders.py:61`
- §3.1 Plan economics — insert — ambiguity — all numeric plan fields optional with defaults, min 0 (`point_value_cents` min 1), `_bp` fields capped at 10,000, band `upper_points` non-negative or null; violations are `ERR_VALIDATION` — `implementation/services/planlib.py:66`
- §3.1 Rank ladder — insert — ambiguity — ≥1 rung, unique `rank_code`, thresholds ≥0, override rates 0..10,000, `rank_order` contiguous 1..n, stored sorted by `rank_order` — `implementation/routes/config.py:80,131`
- §3.1 Jurisdiction — revise — ambiguity — `facilitator_agreement_active` is required (no default) and `state_code` must be exactly two uppercase letters; else `ERR_VALIDATION` — `implementation/routes/config.py:237,242`
- §3.1 Products — insert — ambiguity — `srp_cents` below wholesale is `ERR_VALIDATION` — `implementation/routes/config.py:291`
- §3.3 Order payload — insert — ambiguity — `posted_period_code` resolved only among the ordering consultant's own plan's periods; otherwise `ERR_PERIOD_NOT_FOUND` — `implementation/routes/orders.py:76`, `implementation/services/lookup.py:44`
- §3.3 Payment — insert — ambiguity — volume contribution is `total_volume_points` (not the commissionable subset); `BUSINESS_SUPPLY` feeds neither channel split — `implementation/routes/orders.py:225`
- §3.4 Period creation — insert — ambiguity — `period_start`/`period_end` stored and echoed verbatim, must parse as §2.5 instants — `implementation/routes/periods.py:76`
- §3.4 Qualification row — insert — ambiguity — fresh row's initial values, incl. `sell_through_bp` 0 (not 10,000), `qualified_rank_order` 0, null ranks and `evaluated_at` — `implementation/services/qual.py:24`
- §3.4 Lock — revise — ambiguity — suspension expiry is scoped to consultants of the period's own plan and requires a non-null `active_sanction_until` — `implementation/routes/periods.py:132`
- §3.4 Close — insert — ambiguity — advancement never passes the top rung (counter still resets) — `implementation/routes/periods.py:182`
- §3.4 Close — insert — ambiguity — demotion floors at the `rank_order` 1 rung and does not reset `grace_periods_used` — `implementation/routes/periods.py:196`
- §3.4 Close — insert — ambiguity — the activity-flip grace test reads the count as it stood before this period's increment — `implementation/routes/periods.py:206`
- §3.4 Reopen — insert — ambiguity — `qualification_count`/`total_net_personal_volume_points` refreshed in the same pass; `locked_at`/`closed_at` retained — `implementation/routes/periods.py:251`
- §3.5 Run creation — insert — ambiguity — initial `calculation_sequence` 0, eight totals 0, `statement_count` 0, `correction_flagged` false, five null fields — `implementation/routes/runs.py:79`
- §3.5 Calculate — revise — ambiguity — statements record the **pre-increment** `calculation_sequence` (0 for the first generation, run reads 1 after); `paid_cents`/`carry_forward_cents` start 0 — `implementation/services/commission.py:216,240,251`
- §3.5 DYNAMIC — insert — ambiguity — a compressed `paid_level` above `override_levels` pays nothing and yields no breakdown element — `implementation/services/commission.py:149`
- §3.6 Settlement step 3 — insert — ambiguity — clawback is 0 when the consultant has no qualification row for the reversal period — `implementation/routes/buybacks.py:186`
- §3.6 Settlement — insert — ambiguity — `volume_reversal_period_code` comes from the first submitted line's order when lines span periods — `implementation/routes/buybacks.py:161`
- §3.6 Refund cascade — revise — mismatch — the qualification row is created if absent, and the period's `qualification_count`/`total_net_personal_volume_points` are refreshed whatever the period status (only §2.10's group aggregates freeze) — `implementation/routes/buybacks.py:313,326`
- §3.7 Decision — insert — ambiguity — window conflict is tested only against cases currently in `SANCTIONED` — `implementation/routes/compliance.py:119`
- §3.7 Sanction — insert — ambiguity — `appeal_deadline_at` rendered with three fractional digits, `open_case_count` never below 0, and the `WARNING` branch touches only `highest_sanction_order` — `implementation/routes/compliance.py:180,203`
- §3.7 Sanction — insert — ambiguity — `PROBATION`/`SUSPENSION` change status only from `ACTIVE` (and `PROBATION`); other statuses keep theirs while sanction fields are still recorded — `implementation/routes/compliance.py:192`
- §3.7 Sanction — revise — ambiguity — sanction-driven termination records `termination_reason` `DISCIPLINARY` — `implementation/routes/compliance.py:190`
- §3.9 Disclosure creation — insert — ambiguity — metrics computed at creation; `revision_number` 0 and six null fields — `implementation/routes/disclosures.py:74`
- §3.9 Legal decision — insert — ambiguity — a null `submitted_by_user_id` cannot trip the segregation check — `implementation/routes/disclosures.py:142`
- §4 intro — insert — ambiguity — reopen `reason`, `decision_note`, `reversal_reason`, `appeal_statement`, `reinstatement_note`, `adjustment_reason` are validated (required ones `ERR_VALIDATION` when absent/empty) then not surfaced on any response field — `implementation/routes/periods.py:237`, `implementation/routes/runs.py:150,248`, `implementation/routes/compliance.py:233`, `implementation/routes/consultants.py:94,126`

Deliberately not pinned (kept the diff minimal): unknown-route 404/405 bodies, retention of `reassigned_from_sponsor_consultant_id` after reinstatement, and the `override_breakdown` insertion-order tie-break beyond `paid_level` + source `created_at`.

Orchestrator verification: `workspace/PRD_COMPLETED.md` present — 507 lines / 121,706 chars vs PRD.md's 507 lines / 114,222 chars (+7,484 chars); `diff` against PRD.md touches 28 lines (56 diff lines), no new sections, tail intact through the full error catalogue. Pipeline complete.
