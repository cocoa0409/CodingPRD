# Worklog — task_2141_percentage_rent_retail_sales

## Step 1: Create task directory — 2026-08-22T00:00:00.000Z

Created `tasks/task_2141_percentage_rent_retail_sales/` and `tasks/task_2141_percentage_rent_retail_sales/workspace/` (index 2141 = max existing 2140 + 1).

## Step 2: Generate scaffold — 2026-08-22T16:29:00.000Z

All three files are generated and validated.

## Output

`/home/ubuntu/github/CodingPRD/tasks/task_2141_percentage_rent_retail_sales/`
- `SCAFFOLD.yaml` (§1.0–§1.7)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (§1.8)
- `SCAFFOLD_CORNER_DESIGN.yaml` (§1.9)

**Lint verdict (verbatim):**
```
Coverage
  §1.5 endpoints declared:    57
  §1.1 entities declared:     12
  §1.8 instances scanned:     25
  §1.9 instances scanned:     52
  Calls scanned (§1.8+§1.9):  826

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

## Scaffold contents

**Profile** — `pricing_engine` × `compliance_audit`; layers: dual-variant calc, rate/threshold triggers, cascading side effects, optimistic concurrency. Topology `graph`, state-machine shape `parallel`, role model `segregation_of_duties`, `immediate` consistency. `api_prefix: /retail`. Sits above the Expert band per the "harder than expert" request.

**12 entities** — ShoppingCenter, Tenant, Lease, LeaseYear, SalesReport, SalesExclusion, PercentageRentCharge (self-referential via `supersedes_charge_id`), CoTenancyClause, CoTenancyEvent, KickOutClause, SalesAudit, ReportingLedgerEntry (`common_fields: false`, append-only).

**10 state machines** — SalesReport is cyclic (ACCEPTED→UNDER_AUDIT→DISPUTED→AMENDED→SUBMITTED→ACCEPTED, capped at 2 rounds); PercentageRentCharge carries two parallel axes (`billing_status` × `collection_status`); CoTenancyEvent and KickOutClause branch; LeaseYear cycles via reopen (RECONCILED→RECONCILING); Tenant reverts DARK→OPERATING; Lease cycles ACTIVE↔RELIEF_ACTIVE. Plus SalesExclusion, SalesAudit.

**10 calculations** — `net_reported_sales` (per-code caps + hard caps + aggregate waterfall), `percentage_rent_charge` (CUMULATIVE_YTD vs PERIOD_STANDALONE variants), `annual_true_up` (pinned sum-then-round vs round-per-period), `delinquency_estimate` (pinned evaluation order, estimates never seed estimates), `co_tenancy_relief` (RENT_REDUCTION vs ALTERNATIVE_SALES_RENT), `occupancy_and_co_tenancy_monitor`, `occupancy_cost_ratio`, `kick_out_evaluation`, `reporting_interval_conflicts` (two different interval semantics), `center_sales_trend`.

**2 concurrency rules** — OCC on `LeaseYear.version` (estimate-bill) and `Lease.version` (amendments), both 412.

**57 endpoints**, **13 ordered validation priorities**, **42 error codes**, **5 roles** (CenterAdmin, LeaseAdministrator, TenantUser `entity_backed:Tenant`, Auditor, OwnershipAnalyst).

**§1.8** — 25 instances across all 9 difficulty rules (2–4 each). **§1.9** — 57 instances across all 9 taxonomy sections (52 with recipes, 5 `excluded_because` stubs).

## Verification performed
- Every formula-derived assertion was computed in Python, not estimated — e.g. billing-mode divergence 1,200,000 vs 3,200,000; exclusion waterfall net 17,000,000 with lines 2,250,000/500,000/250,000; the quarterly true-up delta of exactly **1 cent** (60,000,020 summed-then-rounded → 1,200,001 vs 4×300,000); non-compounding estimates 33,000,000 → charge 1,980,000; relief 920,000 vs 720,000; watchlist flip at OCR 1533 bps.
- All `grounds:` refs resolve to declared calculations / transitions / fields / errors / validation priorities / concurrency rule ids.
- Zero unbound `${var}` placeholders; all `excluded_because` targets exist in §1.8; all names unique across both design files.
- No forbidden concurrency vocabulary anywhere; every error code is exercised by at least one design instance; every RBAC role appears on endpoints and vice versa.

One implementation note worth passing along: all §1.5 path parameters are named `{id}` (the lint's FK reverse-reachability check matches that literal segment for sub-resource GETs).

## Step 3: Copy shared files — 2026-08-22T16:29:00.000Z

Copied `INSTRUCTION.md` → `tasks/task_2141_percentage_rent_retail_sales/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-08-22T16:40:00.000Z

The PRD is complete and verified. Written to `workspace/PRD.md` (~13,550 words, 344+ lines), built incrementally in five appends so nothing was lost to an output cap. Neither design index was opened.

**Document skeleton** — §1 Introduction (3 paragraphs); §2 with 11 subsections (2.1 RBAC, 2.2 verbatim envelope, 2.3 Pagination, 2.4 Identity/Timestamps/Version, 2.5 Money & Rounding, 2.6 Logical Clock, 2.7 Snapshot Pinning, 2.8 OCC, 2.9 Request Admission Order, 2.10 Interval Semantics, 2.11 Cascade Discipline & Ledger); §3 with 10 domain-lifecycle subsections; §4 4-column endpoint table; §5 2-column error table. Nothing after §5.

**Verification counts (grep/AST over SCAFFOLD.yaml vs PRD.md):**

```
Field coverage check:
- entities[].fields: 104 required, 104 present, 0 missing
- endpoints[].request_body: 47 required, 47 present, 0 missing
- endpoints[].query_params: 25 required, 25 present, 0 missing
Status: PASS

Rule coverage check:
- validations[] with priority: 13 checked, 13 expressed in prose (§2.9 numbered ladder 1-13), 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed, 0 missing
- state_machines[].transitions: 57 checked across 10 machines, 57 fully expressed, 0 missing
- calculations[]: 10 checked, 10 fully expressed in prose (no pseudocode), 0 missing
- validations[] conditions: 42 error ids checked, 42 matchable to a trigger condition, 0 missing
- endpoints[].side_effects / applies_to: 57 endpoints checked, 57 expressed, 0 missing
- entities[].fields[] structured content: 104 checked, 104 reconstructible, 0 missing
- sibling-branch symmetry: 8 groups checked, 8 with equal density, 0 asymmetric
Status: PASS

Path purity check (§3 only):
- backtick tokens scanned: 888 ; tokens starting with `/`: 0 ; bare HTTP-method tokens: 0
Status: PASS
```

Additional structural checks: §2.2 matches the response-structure template byte-for-byte; all 5 role names present with `identity:` translated (TenantUser as `entity_backed:Tenant`); all state enum values and enum-typed field values appear verbatim in backticks; §4 has exactly 57 rows / 4 columns, §5 exactly 42 rows / 2 columns; zero scaffold jargon; zero fuzzy hedging words.

Notes: the trend-report description in §4 had its calculation reference rewritten to prose; the pinned rounding contrasts driving the true-up (sum-then-round annually vs round-per-period-then-sum) and the two opposite interval conventions (half-open reporting periods vs 30-day-buffered closed audit windows) are each stated explicitly.

## Step 6: Generate implementation — 2026-08-22T17:00:00.000Z

The implementation is complete and verified.

## What was built

`workspace/implementation/` — Python + Flask, ~2,560 lines split across 9 modules so no single write risked the output cap:

| File | Role |
|---|---|
| `start.sh` | Guarded `pip install` (only when flask missing), `exec python3 app.py` |
| `app.py` | Assembly, error handlers, per-request lock, `0.0.0.0:$PORT` (default 10000) |
| `core.py` | Envelope, errors, in-memory store, logical clock, auth, validation, pagination |
| `calc.py` | All 10 calculations + ledger/cascade helpers |
| `serializers.py` | Entity representations (computed `is_delinquent`) |
| `routes_center/lease/report/charge/clause/audit.py` | All 57 endpoints |

## Verification

Server boots from a fresh process via `bash start.sh` (**679 ms** to first response), store empty on every boot (`/retail/tenants` -> `[]`), clock resets to `2026-08-01T00:00:00Z`, no `pip install` on reboot. All 57 routes registered. Six smoke suites pass, exercising: exclusion waterfall (per-line caps, hard ceilings, aggregate trim in descending order), both billing variants, estimate billing with uplift and no-history fallback, the full audit settle->rescind compensation, co-tenancy relief, kick-out triggering/waiver, reconciliation true-up, and the trend report.

## Judgment calls worth flagging

- **Settlement-charge identification on rescind.** The PRD glosses "charges the settlement created" as `issued_at >= settlement moment`. Taken literally with a static logical clock, that also voids the *original* PERIODIC charge from acceptance. Charges are tagged with an internal `_settlement_audit_id` and voided by that instead — verified: original charge stays `ISSUED`, only the supplemental `60000` charge voids.
- **`version` bumps once per resource per request** (deduped via `flask.g`). The estimate-bill narrative says the year's version "advances by 1" while the same cascade moves two counters, so per-request is the only reading that fits.
- **Unspecified values picked:** `ERR_CHARGE_STATE_INVALID` for a DRAFT true-up blocking year closure; ledger `entry_type` on a manual charge void (`ESTIMATE_VOIDED` for ESTIMATE charges, else by delta sign).
- **`reason` treated as required** on dispute/amend/void/rescind/reopen — the scaffold marks optional inputs with `?` and these are unmarked. Most likely to cause a false 400 if test factories omit it.
- **Clock/business timestamps** format as `...T00:00:00Z` when sub-second is zero; `created_at`/`updated_at` always carry 3 fractional digits per §2.4.

No entity seeding anywhere.

## Step 5: Generate unit tests — 2026-08-22T17:26:00.000Z

Test infrastructure and suite are complete and verified.

## What was generated

**`test_helpers/`** (9 files, ~2,000 lines)
- `types.py` — 20 status/role enums, entity TypedDicts. `ReportingLedgerEntry` deliberately carries only `id`/`created_at` (`common_fields: false`).
- `api_client.py` — all 57 endpoint methods on `ApiClient(GenericApiClient)`, including the two root-level clock endpoints.
- `api_errors.py` — 42-code enum + HTTP map, registered via `set_error_http_status_map`.
- `assertions.py` — per-entity assertions, ledger append-only check (asserts `updated_at`/`version` keys are *absent*), plus `assert_instant_equals` / `plus_days` and invariant checkers (`assert_ledger_balances`, `assert_relief_credit_consistent`).
- `factories.py`, `constants.py` (cap tables, thresholds, standard test economics), `test_users.py`, `fixtures.py` (5 tiers: state progression -> hierarchy -> lifecycle shortcuts -> threshold targeting like `setup_delinquent_report` / `setup_triggered_kick_out` / `setup_relief_active_lease`), `__init__.py` barrel.

**`test_suite/`** — `conftest.py` + 10 domain-named files, **102 tests**.

## Audit results (scripted, all green)

- **Queue A**: all **25** difficulty instances have **>=2** tagged tests (50 tests).
- **Queue B**: all **52** non-stub corner instances have **>=1** tagged test (52 tests). The 5 `excluded_because:` stubs were verified to cross-reference real difficulty instances and were **not** translated.
- Every test carries exactly one `Design:` line; no untagged, dual-tagged, stub-tagged or unresolvable tags.
- **172 PRD citations** all survive a whitespace-normalized literal match against `PRD.md`.
- No `skip`/`skipif`/`xfail`; no scaffold references in comments or docstrings; pyflakes clean; `pytest --collect-only` collects 102.

## Judgement calls worth flagging

- **Timestamps compared as instants, not strings.** The design indices assert literals like `"2026-10-11T00:00:00.000Z"`, but the PRD only pins three fractional digits for `created_at`/`updated_at` — not for business instants. `assert_instant_equals` parses both sides; the whole-day arithmetic under test is still asserted exactly.
- **One assertion dropped** from `lease_natural_breakpoint_is_computed_from_base_rent_and_rate`: the design's `artificial_breakpoint_cents is null` on a NATURAL lease is a default-value/computed-field silence. The rest of that instance is asserted.
- Verified independently rather than trusting the yaml: the 3,000,000 waterfall trim, the `true_up_delta_cents == 1` sum-then-round residue, the 33,000,000 non-compounding estimate and its 1,980,000 delta charge, the 1533 bps watchlist flip, and the 2500/12500/2400 trend figures.

## Step 7: Run tests and iterate — 2026-08-22T17:35:00.000Z

The loop converged on the first sweep. All 8 concurrent rounds returned 102/102.

**Iterations run:** 1 (one full 8-round parallel stability sweep; no second iteration needed).

**Sweep result:** rounds 1–8 all `passed == total == 102`, `failed=0, errors=0, skipped=0`. Round wall time ~140 s each; the 8 ran concurrently on distinct runner-allocated ports. Verified the JSON is genuine rather than a collection short-circuit: each `results.${i}.json` carries 102 per-test entries and the distinct status set is exactly `{"passed"}`. Union of failing tests across all 8 rounds is empty, so no test entered the diagnostic protocol.

**Tests deleted:** none.

**Fixes applied to `test_helpers/`:** none required.

**Fixes applied to `implementation/`:** none required.

**Invariant checks performed alongside the sweep:**
- No `pytest.mark.skip` / `skipif` / `xfail` anywhere in `test_suite/` or `test_helpers/`.
- No startup seeding or on-disk persistence in `workspace/implementation/` — no SQLite, no JSON dump, no file `open()`. Storage is in-memory only.

**Flakiness note:** the concurrency-sensitive areas (settlement-charge identification on rescind, per-request `version` dedup via `flask.g`, the estimate-bill cascade advancing two counters) held across all 8 concurrent rounds under `--isolation per-test-server`.

Orchestrator re-verified all 8 result files independently: 102/102 passed, 102 entries each, status set `{passed}`.

## Step 8: Finalize PRD — SKIPPED — 2026-08-22T17:36:00.000Z

Skip condition met: Step 7 exited on the first 8-round sweep with 0 deletions, 0 `test_suite/` fixes, 0 `test_helpers/` fixes, and 0 `implementation/` fixes. `PRD.md` already determined every behavior the test suite exercised. No `PRD_FINALIZED.md` produced.

## Step 9: Complete PRD — 2026-08-22T17:41:00.000Z

All edits were in-paragraph; no new sections or paragraphs.

**Source vs output:** `workspace/PRD.md` 456 lines / 95,587 bytes -> `workspace/PRD_COMPLETED.md` 456 lines / 98,836 bytes (**+3,211 chars**, 0 line delta).

**Counts:** 21 changes — **16 ambiguity-pins**, **5 mismatch-revisions**.

### Changes

- **2.4 Resource Identity/Versions** — insert — ambiguity — a request advances a resource's `version` by at most 1 no matter how many fields its cascade rewrites; a no-op recomputation advances nothing — `core.py:170-183`, `app.py:38`
- **2.6 Logical Clock** — insert — ambiguity — rendering of `current_utc` and business-event timestamps (3 fractional digits only when non-zero ms) vs always-3-digit `created_at`/`updated_at` — `core.py:56-63`, `core.py:203-212`
- **3.1 Standing Up a Center** — insert — ambiguity — duplicate center `code` refused with `ERR_INVALID_REQUEST` (400) — `routes_center.py:52-54`
- **3.2 Lease Economics** — insert — ambiguity — amendment resets `effective_monthly_rent_cents`/`relief_monthly_credit_cents` unless `co_tenancy_status` is `RELIEF_ACTIVE` — `routes_lease.py:187-189`
- **3.3 Opening a Reporting Year** — insert — ambiguity — lease status does not gate year creation — `routes_lease.py:211-223`
- **3.5 Acceptance / Watchlist** — revise — mismatch — occupancy-cost re-runs on `ISSUED` and `ISSUED -> VOID` only — `routes_charge.py:89-96`
- **3.7 Audit** — insert — ambiguity — settlement requires report still `UNDER_AUDIT`, else `ERR_REPORT_STATE_INVALID` — `routes_audit.py:118-119`
- **3.7 Audit** — revise — mismatch — rescission voids exactly the charge this audit's own settlement produced (tracked provenance) — `routes_audit.py:186-190`, `calc.py:233-248`
- **3.7 Audit (dispute)** — insert — ambiguity — dispute requires year `OPEN` or `RECONCILING` — `routes_report.py:283`
- **3.7 Audit (amend)** — insert — ambiguity — amendment requires year `OPEN` or `RECONCILING` — `routes_report.py:306`
- **3.8 Charges** — revise — mismatch — `supersedes_charge_id` never populated; a late actual voids the `ESTIMATE` charge outright — `calc.py:233-248`, `routes_report.py:178-192`
- **3.8 Charges (void)** — insert — ambiguity — void ledger `entry_type` rules — `routes_charge.py:91-94`
- **3.8 Charges (payments)** — insert — ambiguity — payments require owning year not `CLOSED` — `routes_charge.py:109`
- **3.9 Co-Tenancy (activate-relief)** — insert — ambiguity — clause/lease state error codes — `routes_clause.py:122-125`
- **3.9 Co-Tenancy (cure)** — insert — ambiguity — `CURE_PENDING -> CURED` leaves `relief_ended_at` null — `routes_clause.py:151-155`
- **3.9 Kick-Out (attach)** — insert — ambiguity — optional `waiver_consideration_cents` >= 0 at attachment — `routes_clause.py:197-199`
- **3.9 Kick-Out (exercise)** — insert — ambiguity — lease outside `ACTIVE`/`RELIEF_ACTIVE` -> `ERR_LEASE_STATE_INVALID` — `routes_clause.py:242-243`
- **3.9 Kick-Out (waive)** — insert — ambiguity — omitting `waiver_consideration_cents` leaves existing value — `routes_clause.py:291-292`
- **3.9 Kick-Out (waive lapse)** — revise — mismatch — `TRIGGERED -> EXPIRED` resets `waiver_consideration_cents` to 0; approver untouched; SoD test fires ahead of window test — `routes_clause.py:279-288`
- **3.10 Closure** — insert — ambiguity — unissued `DRAFT` charge blocks closure with `ERR_CHARGE_STATE_INVALID` — `routes_lease.py:331-333`
- **3.10 Trend Report** — insert — ambiguity — `year_index` required query param >= 1 — `routes_center.py:79-83`

### Notes
- Everything else in `implementation/` (exclusion waterfall caps and trim order, both billing variants, estimate lookback and uplift, true-up, relief variants, occupancy monitor, admission-ladder ordering, pagination, envelope shape, ledger append rules) was already uniquely pinned by the PRD and left untouched.
- Tests were used only as auxiliary cross-reference; no assertion was treated as authority.
