# Worklog — task_1139_contingent_labor_rate_card_statement_work

## Step 1: Create Task Directory — 2026-08-11T00:00:00.000Z

Task directory `tasks/task_1139_contingent_labor_rate_card_statement_work/` and its `workspace/` subdirectory were pre-assigned and already exist; auto-index scan skipped per instructions. Step 1 treated as done.

Scenario: 1139. Contingent Labor Rate Card & Statement-of-Work Management (contingent workforce program office): rate card by role/skill/geography & markup transparency, requisition vs SOW classification & misclassification risk, supplier tiering & distribution rules, milestone/deliverable acceptance & payment, tenure limits & conversion-to-employee fees, timesheet approval & rate compliance audit, worker onboarding/offboarding coordination, spend visibility & consolidation savings

Difficulty parameter: "generate task hard than expert level!" (passed through to scaffold generator at Step 2 only).

## Step 2: Generate Scaffold — 2026-08-11T01:00:00.000Z

Scaffold generation complete. All three artifacts are written to `/home/ubuntu/github/CodingPRD/tasks/task_1139_contingent_labor_rate_card_statement_work/` and the lint verdict is clean.

**Lint verdict (verbatim):**
```
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
  §1.5 endpoints declared: 74 | §1.1 entities: 13 | §1.8 instances: 19 | §1.9 instances: 50 | calls scanned: 872
```

**What was built** (deliberately beyond the Expert band):

- **SCAFFOLD.yaml** — 13 entities (Supplier, RateCard, Engagement, DistributionOffer, Worker, Assignment, Timesheet, Milestone with parallel acceptance×payment dimensions, Invoice, InvoiceLine (polymorphic XOR source), ConversionRequest, ComplianceAudit, append-only SpendLedgerEntry), 11 state machines, 12 calculation rules, 29 ordered validation rows, 74 endpoints, 31 error codes, 6 roles. Archetype: compliance/audit + pricing-engine; flat topology; segregation-of-duties role model (same-role SoD on invoice finalize→mark-paid via `finalized_by_user_id`); 2 OCC concurrency rules (`engagement-amend-stale-version`, `rate-card-revision-stale-version`); logical clock endpoint with the mandated `2026-05-01T00:00:00Z` default.
- **SCAFFOLD_DIFFICULTY_DESIGN.yaml** — 19 instances, ≥2 per rule, with the required differentiations: dual-variant calcs on Timesheet billing vs ConversionRequest fees; combinatorial modes (a) tier-score weighted min/max, (b) per-line-then-sum invoice rounding (63008 vs 63007 trap), (c) fee tiered on pre-fee subtotal (150000 vs post-fee-total divergence); cyclic Engagement rework loop vs parallel Milestone dimensions; depth-3 cascade (milestone accept → committed spend → auto BUDGET_UTILIZATION audit → supplier violation counter) vs depth-2 close→terminate→offboard chain; priority conflicts (state vs fiscal) and (safety vs referential); tenure `>= 730` boundary vs zero-line invoice boundary; two cross-entity gates on different pairs; half-open rate-card windows vs closed-inclusive worker double-booking; spend-dollar vs offer-count conservation invariants. All formula-derived asserts are precomputed literals (2287671, 2287671 vs 2500000 at identical tenure 62, etc.).
- **SCAFFOLD_CORNER_DESIGN.yaml** — 50 full instances + 8 `excluded_because` stubs across all nine guide sections (entities, state_machines, calculations, validations, endpoints, errors, rbac, cross_cutting, consistency), covering every error code, RBAC denials incl. entity-backed ownership and Anonymous→401, OCC stale/fresh paths, expire-sweep checkpoint, and pagination/filter interplay.

**Bugs caught and fixed during self-review** (beyond lint): `rc_v` OCC captures moved to post-activation responses (activate bumps `version`); the markup corner flipped to card-cap-binds because PROBATION suppliers are distribution-ineligible; R1b's EB offer index corrected to `$.data[1].id` (PREFERRED ranks first); unreachable `TENURE_BREACH` enum value replaced with reachable `TENURE_RISK` (≥700-day early warning); milestone counters declared and wired into deliver/accept side effects so `supplier_tier_score` is fully grounded. No sibling task under `tasks/` was read at any point.

## Step 3: Copy Shared Files — 2026-08-11T01:00:30.000Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` to `tasks/task_1139_contingent_labor_rate_card_statement_work/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-08-11T01:12:00.000Z

All checks pass. The PRD has been generated at `/home/ubuntu/github/CodingPRD/tasks/task_1139_contingent_labor_rate_card_statement_work/workspace/PRD.md`.

## What was done

- Read the generator skill (`skills/prd-bench-doc-generator/SKILL.md`), the fixed §2.2 verbatim block (`section-2.2-response-structure.md`), and the scaffold (`SCAFFOLD.yaml`). The two test-targeting design files (`SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`) were not opened.
- Generated a prose PRD with: §1 Introduction (2 paragraphs, system-goal/risk angle); §2 with 11 domain-derived subsections (RBAC with per-role identity translation, verbatim §2.2, pagination, logical clock, resource identity, money/rounding, validation precedence tiers, OCC, rate card windows, supplier counters, spend ledger); §3 with 9 scattering subsections (rate cards, supplier governance, engagement classification/closure, distribution/offers, workers/assignments/tenure, timesheets, milestones, invoices, conversion/audits/spend visibility); §4 endpoint table (74 rows, 4 columns); §5 error catalogue (31 rows, 2 columns).
- All 12 calculation rules expressed as precise prose (integer basis-point markup comparison, PROVISIONAL/FINAL timesheet variants with ceiling clamp, per-line-pinned consolidation with the 63007-vs-63008 counterfactual, pre-fee-keyed tiered processing fee with the 9,999,999-cent divergence example, consolidation savings, tier scoring with insufficient-data and empty-pool branches, both conversion-fee variants with the tenure-62 example, closed-interval tenure accumulation, committed-spend state filters with the 95% crossing rule, distribution selector ranking with null-as-70, misclassification risk, audit evaluation).

## Hard Contract Reports

```
Field coverage check:
- entities[].fields: 92 required, 92 present, 0 missing
- endpoints[].request_body/input: 59 required, 59 present, 0 missing (fixed 'decision')
- endpoints[].query_params/path_params/output-keys: covered (148 total identifiers incl. errors/roles, 0 missing)
Status: PASS
```

```
Rule coverage check:
- validations[] priority ordering: expressed as 10 precedence tiers in §2.7 plus intra-endpoint ordering for assignment booking; 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (expected_engagement_version → ERR_STALE_ENGAGEMENT_VERSION/412; expected_rate_card_version → ERR_STALE_RATE_CARD_VERSION/412)
- state_machines[].transitions: 40 checked, all expressed incl. side-effect cascades (close/suspend/approve/accept/finalize/mark-paid/void/complete), 0 missing
- calculations[]: 12 checked, 12 fully expressed in precise prose, 0 missing
- validations[] conditions: all 26 checks matchable to their error_id in §2.7/§3, incl. full applies_to scope enumeration, 0 missing
- entities[].fields[] structured content: defaults/initials/computed semantics stated (counters, flags, null-until fields, common_fields:false for InvoiceLine/SpendLedgerEntry), 0 missing
- sibling-branch symmetry: ACCEPT/DECLINE, PENDING/REJECTED deliver, OPEN/FILLING/ACTIVE close, approve/reject, resolve/dismiss all at equal density
Status: PASS
```

```
Path purity check (§3 only):
- backtick tokens scanned: 618
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

Table shape verification: §4 has 74 rows matching the 74 scaffold endpoints (4 columns each); §5 has 31 rows matching the 31 scaffold errors (2 columns each).

## Step 5: Generate Unit Tests — 2026-08-11T01:45:00.000Z

Generation complete. Summary of what was produced and the audit results:

## Output

**`test_helpers/`** (9 files) at `/home/ubuntu/github/CodingPRD/tasks/task_1139_contingent_labor_rate_card_statement_work/test_helpers/`:
- `types.py` — 13 entity TypedDicts + 20 status/role enums; `InvoiceLine` and `SpendLedgerEntry` correctly carry only `id`/`created_at` (no `updated_at`/`version`).
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per PRD endpoint (80 methods incl. inherited).
- `api_errors.py` — all 31 error IDs with HTTP status map, registered via `set_error_http_status_map`.
- `assertions.py` — per-entity assertions; append-only kinds assert *absence* of `updated_at`/`version`.
- `factories.py`, `constants.py` (all PRD thresholds: 730-day tenure, fee tiers, markup caps, fanout 3, etc.).
- `test_users.py` — shared constants for opaque roles; mandatory per-instance `make_supplier_coordinator_headers` / `make_worker_headers` builders for entity-backed roles; named `make_finance_analyst_headers("fin-1"/"fin-2")` for the SoD flows.
- `fixtures.py` — composite chains: `setup_bookable` (through ACCEPTED offer), `setup_staffed_assignment` (through ACTIVE assignment), `setup_sow_engagement`, timesheet lifecycle shortcuts, `find_open_invoice_id`; all support `rate_card=`/`supplier=` reuse and `clock=None` for multi-engagement scenarios.

**`test_suite/`** — `conftest.py` + 10 test files, **107 test functions**: 39 Difficulty-tagged, 68 Corner-tagged.

## Audit results (all machine-checked)

- Every difficulty instance (19) has ≥2 tests; every non-stub corner instance (50) has ≥1; all 8 `excluded_because:` stubs correctly untranslated (cross-references verified resolvable).
- Every test docstring ends with exactly one `Design:` tag resolving to a real `name:` in the source yaml.
- Every docstring's PRD citation contains a ≥6-word segment that greps verbatim in `PRD.md`.
- No `skip`/`skipif`/`xfail` markers; no "scaffold" references in generated code; `py_compile` + import + `pyflakes` all clean.

## Key adjudication decisions

- **Priority-pair instances generated** (not silence-skipped): PRD §2.7 explicitly numbers the precedence tiers and §3.5/§2.7-6 explicitly state suspended-supplier outranks referential — coverage + unique derivability both hold.
- **`rate_card_creation_defaults`**: the asserted `version == 1` was dropped — PRD says only "starts low and increments by one," which does not uniquely derive 1; all other assertions (DRAFT, null `supersedes_id`, UUID, ISO timestamps, ignored system-field input) are PRD-pinned.
- **`spend_summary_computed_read` generated** with the instance's values (committed 90000, invoiced/paid 91350, savings 0, violations 0): `total_cents` is the invoice's canonical total, making "invoiced"/"paid" sums uniquely readable.
- Void-invariant running-balance assertion uses the *set* of balances `{0, 332500}` rather than "latest by created_at," since the frozen clock ties `created_at` — the set is still PRD-derived (each entry records the balance immediately after itself).

## Step 6: Generate Implementation — 2026-08-11T01:45:00.000Z

Implementation complete and verified.

## What was built

A Python + Flask in-memory REST API at `/home/ubuntu/github/CodingPRD/tasks/task_1139_contingent_labor_rate_card_statement_work/workspace/implementation/`:

- **`start.sh`** — guarded dependency install (`pip install` only when `flask` is missing, so per-test reboots don't contend), `exec python3 app.py` in foreground, `0.0.0.0:$PORT` (default 10000).
- **`app.py`** — blueprint registration, JSON-envelope error handlers for `ApiError`, 404/405, and a 500 safety net.
- **`db.py`** — empty-on-boot store (no seeding anywhere), logical clock defaulting to exactly `2026-05-01T00:00:00Z`, millisecond-precision `YYYY-MM-DDTHH:MM:SS.mmmZ` timestamp formatting, `version` starting at 1 with `updated_at`/`version` bumps on every mutation (InvoiceLine/SpendLedgerEntry carry only `id`+`created_at`).
- **`envelope.py` / `errors.py` / `security.py` / `validators.py`** — `meta`/`response_type`/`data` envelope with pagination fields (`limit`/`offset`/`total_count`/`has_more`, defaults 10/0, clamped 1–100), full error catalog, `X-User-ID`/`X-User-Role` auth with the five declared roles, and shape validators (dates, ≤2dp hours via `Decimal`, enums, ints rejecting bools).
- **`services.py`** — all eleven scaffold calculations with pinned semantics: integer cross-multiplication markup check (tier caps 0.25/0.20/0.15), PROVISIONAL/FINAL timesheet billing with governing-card ceiling clamp, per-line-pinned invoice consolidation, pre-fee-subtotal tiered processing fee (1.5%/1.0% at 10,000,000), consolidation savings (5000/line−1), weighted tier score with insufficient-data branch and inclusive 85/70 bands, SCHEDULE/PRORATA conversion fee (verified the PRD's 62-day example: 2,287,671), closed-interval tenure with the strict `< 730` gate (exactly 730 rejected), committed-spend with one-shot 95% `BUDGET_UTILIZATION` crossing, deterministic distribution ranking (tier → score desc null-as-70 → created_at → supplier_code), misclassification risk, and the audit-run evaluation.
- **14 route modules** covering all 74 endpoint routes from the scaffold table, with validation precedence per PRD §2.7 (auth → role → shape → existence → state → safety → constraint → temporal → referential → fiscal, fiscal ordered ceiling→markup→floor) and all cascades (suspend→offer withdrawal, close→assignment termination→worker offboarding, approve/accept→ledger+invoice-line+committed-spend+budget-audit, void→full compensation, invoice finalize/void→milestone payment dimension, conversion-complete→worker EXITED/CONVERTED).

## Verification

Three smoke suites run against live boots covered: auth/RBAC matrix (incl. Worker exclusions), clock set/default, card window half-open overlap and adjacency, both OCC 412 paths, distribution ranking and empty-pool 422, offer accept bubble-up, assignment fiscal/tenure/double-booking guards in precedence order, 60.00-hours boundary, provisional/final amounts (59.5×9000=535500), ledger running balances, auto-invoice month periods, fee tier (8033 on 535500), SoD 403, invoice void line migration, milestone redelivery loop and payment dimension, PRORATA vs SCHEDULE fees, budget-audit crossing, tier evaluation (score 67 → PROBATION), suspend/close cascades, expire-sweep timing, and pagination meta. All passing; the only failures during testing were smoke-test-side expectation errors (the ACTIVE-assignment tenure clamp-to-clock behavior is spec-correct).

Notable judgment calls where the PRD is silent: nonexistent body foreign keys return 404; duplicate `supplier_code`/worker email return 400 (no dedicated catalog entries); timestamps normalize to 3-fractional-digit form including `current_utc`; `total_cents` maintains `subtotal + fee` invariant on OPEN invoices; milestone-deliver ownership (403) precedes the engagement-ACTIVE check (409) per priority order.

## Step 7: Run Tests and Iterate — 2026-08-11T02:24:00.000Z

Pre-sweep route verification (orchestrator): implementation registers exactly the 74 (method, path) route pairs SCAFFOLD.yaml declares — 0 missing, 0 extra.

Two consecutive clean 8-round sweeps (16/16 rounds, 107/107 tests each). Notably, the confirmation sweep ran while the port registry showed 16 holders — co-tenant benchmark pipelines were actively sweeping concurrently, and the hardened boot survived the contention.

## Summary

- **Iterations run**: 3 sweeps (initial diagnosis + post-fix + confirmation), each a full 8-round parallel sweep. Final two sweeps: all 8 rounds `passed == total` (107/107, 0 failed, 0 errors in every round).

- **Tests deleted**: none.

- **Fixes applied to `test_suite/`**:
  - `/home/ubuntu/github/CodingPRD/tasks/task_1139_contingent_labor_rate_card_statement_work/test_suite/test_05_assignments_workers.py` — `TestFiscalRails::test_bill_above_ceiling_rejected_and_pay_below_floor_rejected` (STEP 2 test bug). The pay-floor probe payload was `bill_rate_cents: 9000, pay_rate_cents: 4999` — an ~80% markup that trips `ERR_MARKUP_ABOVE_CAP`, which PRD §2.7/§3.5 explicitly orders before the pay-floor check ("within the fiscal tier the bill-rate ceiling is checked first, then markup, then the pay floor"). The implementation was PRD-correct; the test violated PRD precedence by violating two guards while asserting the lower-precedence one. Changed the probe to `bill_rate_cents: 5000, pay_rate_cents: 4999` (~0.02% markup, within ceiling), so only the pay-floor guard fires and `ERR_PAY_BELOW_FLOOR` is the uniquely-determined PRD outcome. Assertion strength unchanged (still exact `error_id`).

- **Fixes applied to `test_helpers/`**: none (no fixture/factory/header bugs found; `setup_bookable` defaults are PRD-consistent).

- **Fixes applied to `implementation/`** (both target the flaky `could not be restarted` setup errors, which migrated between tests across sweeps — root cause was environmental: ~7 co-tenant benchmark pipelines running their own 8-round sweeps on the same 8-core host, pushing boot latency past the runner's fixed 15s health-poll window):
  - `/home/ubuntu/github/CodingPRD/tasks/task_1139_contingent_labor_rate_card_statement_work/workspace/implementation/app.py` — `__main__` block now retries `app.run()` on `OSError` (up to ~20s, inside the runner's poll window) so a not-yet-released listener port after the harness's SIGKILL no longer crashes the boot. Signals still kill the process outright; no respawn-after-kill risk, no state survives restarts (store remains purely in-memory).
  - `/home/ubuntu/github/CodingPRD/tasks/task_1139_contingent_labor_rate_card_statement_work/workspace/implementation/start.sh` — replaced the per-boot `python3 -c "import flask"` probe subprocess with a `.deps_installed` sentinel fast path (sentinel written only after an importable check succeeds; original `pip install -q -r requirements.txt` fallback preserved verbatim, needed because pip is PEP 668-blocked here). Steady-state boot is now a single `exec python3 app.py` with zero probe subprocesses, minimizing exposure to the 15s poll window under fork/exec storms. The verbatim `cd <implementation dir> && bash start.sh` start-command form was not touched.

No implementation behavior was weakened, no endpoints/fields added beyond PRD, no tests skipped or assertions downgraded.

Orchestrator disk verification: all 8 `results.{1..8}.json` files present, each `passed=107 total=107 failed=0 errors=0`.

## Step 8: Finalize PRD — 2026-08-11T02:27:00.000Z

`/home/ubuntu/github/CodingPRD/tasks/task_1139_contingent_labor_rate_card_statement_work/workspace/PRD_FINALIZED.md` written — a byte-identical copy of `PRD.md` (verified with `diff -q`). Zero edits were warranted: no `<step_7_diff>` item revealed PRD silence or a PRD/implementation mismatch.

**Line counts / delta**
- `PRD.md`: 343 lines; `PRD_FINALIZED.md`: 343 lines; delta 0 lines, 0.0%.

**Per-item analysis (why each Step 7 item produced no PRD edit)**

- `test_suite/test_05_assignments_workers.py` test fix (fiscal-guard precedence probe) — pure test bug; PRD already pins the behavior. No edit.
- `implementation/app.py` OSError bind-retry — boot-hardening with no PRD-visible behavior. No edit.
- `implementation/start.sh` `.deps_installed` sentinel fast path — boot-hardening with no PRD-visible behavior. No edit.

**Pre-edit search log** (no edit was committed, but the mandatory enumeration was performed for each candidate)

1. **Fiscal-tier ordering at assignment booking**
   - (a) Subject: precedence of `ERR_RATE_ABOVE_CEILING` → `ERR_MARKUP_ABOVE_CAP` → `ERR_PAY_BELOW_FLOOR`.
   - (b) Paths enumerated: `implementation/routes/assignments.py:127-132` (the only site raising all three errors — checks in exactly the PRD order: ceiling line 127-128, markup line 129-130, floor line 131-132); `implementation/services.py:47-50` (`markup_allowed`); `implementation/routes/audits.py:76` (uses `markup_allowed` only to raise a `MARKUP_EXCEEDED` finding row, not an ordered error rejection; never touches the ceiling/floor errors); `implementation/errors.py:27-29` (error definitions). PRD anchors: §2.7 line 108 ("within the fiscal tier the bill-rate ceiling is checked first, then markup, then the pay floor") and §3.5 line 178 ("Only then do the fiscal guards run, in this order: ...").
   - (c) No wording adjustment made — the PRD already uniquely determines the order and the implementation matches it verbatim; the Step 7 fix only corrected a test probe that violated two guards simultaneously.

2. **`app.py` `__main__` retry-on-OSError**
   - (a) Subject: server boot/port-binding behavior.
   - (b) Paths enumerated: `implementation/app.py:69-84` (retry loop reading `PORT`, binding `0.0.0.0`); `implementation/start.sh:17` (`exec python3 app.py`); `workspace/INSTRUCTION.md` (the entire start contract — PORT env, 0.0.0.0, foreground — lives here, not in the PRD). The PRD contains no deployment/boot section, so there is no PRD text to pin this against; the retry is invisible to every API behavior the PRD specifies.
   - (c) No wording adjustment made.

3. **`start.sh` dependency sentinel**
   - (a) Subject: dependency-install fast path at boot.
   - (b) Paths enumerated: `implementation/start.sh:9-16` (sentinel check, `import flask` probe, `pip install` fallback); `implementation/app.py` (unchanged server entry). Same conclusion as item 2: no PRD-visible behavior; the verbatim `bash start.sh` start-command form and the foreground `exec` contract are preserved.
   - (c) No wording adjustment made.

## Step 9: Complete PRD — 2026-08-11T02:35:00.000Z

All 22 edits are applied as single-line in-place revisions. Work is complete.

## Summary

**Files**: `PRD_FINALIZED.md` (source) — 343 lines / 63,687 chars → `PRD_COMPLETED.md` — 343 lines / 67,258 chars (char-delta +3,571; line count unchanged, all edits inline).

**Counts**: 22 changes total — 22 ambiguity-pins, 0 mismatch-revisions (implementation matched every behavior the PRD actually pinned; all gaps were PRD silence).

**Changes** (section — insert/revise — class — what changed — impl evidence):

- §2.3 Pagination — revise — ambiguity — limit clamped to [1,100], offset clamped to ≥0, non-integer values yield `ERR_VALIDATION` (400), `has_more` = (offset + returned) < total_count, created_at ties broken by insertion order — implementation/validators.py:201-214, envelope.py:41
- §2.4 Logical Clock — insert — ambiguity — offset-less `to_iso8601` interpreted as UTC — implementation/validators.py:186-187
- §2.5 Identity — revise — ambiguity — `version` starts at 1 (was "starts low") — implementation/db.py:76
- §2.7 Precedence tier 4 — insert — ambiguity — body-carried resource identifiers (`supplier_id`, `worker_id`, `assignment_id`, `offer_id`, `rate_card_id`) resolve at the existence tier with `ERR_NOT_FOUND` — implementation/routes/assignments.py:58-70, workers.py:30-31, conversions.py:35-40, invoices.py:48-49
- §2.8 OCC — insert — ambiguity — version comparison evaluated after shape, existence, and state-validity tiers on both guarded endpoints — implementation/routes/rate_cards.py:123-136, engagements.py:171-182
- §3.1 Rate card creation — insert — ambiguity — no ordering validation between `effective_from` and `effective_to` at creation — implementation/routes/rate_cards.py:42-54
- §3.2 Supplier onboarding — insert — ambiguity — duplicate `supplier_code` rejected with `ERR_VALIDATION` (400) — implementation/routes/suppliers.py:30-32
- §3.3 Engagement creation — insert — ambiguity — `classification_note` born null — implementation/routes/engagements.py:67
- §3.3 Classification decision — revise — ambiguity — any `risk_override_rationale` supplied on APPROVE becomes `classification_note` (not only HIGH-risk overrides) — implementation/routes/engagements.py:128-129
- §3.3 Engagement closure — insert — ambiguity — FILLING-path terminations also stamp `actual_end_date` from the logical clock (PRD stated it only for the ACTIVE path) — implementation/routes/engagements.py:211-218
- §3.4 Distribution — insert — ambiguity — response is an array envelope with meta limit/total_count = offers created, offset 0 — implementation/routes/engagements.py:162-164
- §3.5 Tenure — insert — ambiguity — booking/extension projection formula pinned: carryover + existing spans through clock date + full closed span of the prospective assignment — implementation/services.py:97-119
- §3.5 Extension — insert — ambiguity — non-strictly-later `new_end_date` rejected with `ERR_VALIDATION` (400) — implementation/routes/assignments.py:208-209
- §3.6 Hours — insert — ambiguity — negative hour values rejected with `ERR_VALIDATION` (400) — implementation/validators.py:149-150
- §3.6 Approval — insert — ambiguity — supplied `approved_hours` validated as hour value but exempt from the 60.00 ceiling — implementation/routes/timesheets.py:158,166
- §3.6 Approval — insert — ambiguity — with no governing ACTIVE card at approval time the effective rate is the unclamped `bill_rate_cents` — implementation/routes/timesheets.py:168-171
- §3.6 Void — insert — ambiguity — compensation is exactly the three listed effects; a raised BUDGET_UTILIZATION audit is not retracted and `budget_audit_raised` stays true — implementation/routes/timesheets.py:225-239
- §3.7 Delivery — insert — ambiguity — `delivery_note` accepted but not persisted on the milestone — implementation/routes/milestones.py:90, serializers.py:88-93
- §3.8 Invoice void — insert — ambiguity — voided invoice keeps fee/total/savings from finalization while `line_count`/`subtotal_cents` drop to zero — implementation/routes/invoices.py:160-162
- §3.9 Conversion filing — insert — ambiguity — assignment not belonging to worker → `ERR_VALIDATION` (400); assignment not ACTIVE → `ERR_INVALID_STATE` (409) — implementation/routes/conversions.py:41-44
- §3.9 Conversion complete — revise — ambiguity — referenced assignment terminated only if still ACTIVE; worker still moves to EXITED regardless — implementation/routes/conversions.py:133-143
- §3.9 Audit run — insert — ambiguity — no governing ACTIVE card ⇒ no OVER_RATE/MARKUP_EXCEEDED findings; run returns array envelope with meta limit/total_count = finding count — implementation/routes/audits.py:56-105
- §3.9 Spend summary — insert — ambiguity — precise aggregate definitions (committed = Σ ledger delta_cents; invoiced/savings over FINALIZED+PAID `total_cents`; paid over PAID; open violations = OPEN or ACKNOWLEDGED audits) — implementation/routes/spend.py:45-68

Framework plumbing deliberately left unpinned (405→404 mapping, 500 fallback handler in app.py) as outside the PRD's API-contract prose.

Orchestrator final verification: `workspace/PRD_COMPLETED.md` exists (343 lines); worklog reaches "## Step 9"; all 8 sweep rounds `passed=107 total=107 failed=0 errors=0`. Pipeline complete.
