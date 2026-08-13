# Worklog — task_1492_airport_concession_program_rent

## Step 1: Create Task Directory — 2026-08-13T12:36:00.000Z

Task directory `tasks/task_1492_airport_concession_program_rent/` and `workspace/` pre-created and pre-assigned by the invoking command; treated as DONE per instructions.

## Step 2: Generate Scaffold — 2026-08-13T13:31:00.000Z

**Files written** (all under `/home/ubuntu/github/CodingPRD/tasks/task_1492_airport_concession_program_rent/`):
- `SCAFFOLD.yaml` — §1.0–§1.7 (no difficulty/corner keys)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single top-level `scaffold_difficulty_design:` (§1.8)
- `SCAFFOLD_CORNER_DESIGN.yaml` — single top-level `scaffold_corner_design:` (§1.9)

**Counts:**
- Entities: **11** (Tenant, Lease, SalesReport, RentSettlement, Payment, AuditCase, ACDBEReview, TIDraw, PolicyViolation, OperatingHoursWaiver, EnplanementSnapshot)
- State machines: **9** (all entities except Tenant and EnplanementSnapshot)
- Endpoints: **47** (incl. `POST /_clock/set_current_utc` with pinned default `2026-08-01T00:00:00Z`)
- Difficulty instances: **18** (2 per rule × 9 rules)
- Corner instances: **49** (46 full recipes + 3 `excluded_because:` stubs)
- Errors: **34**; validations: 34 ordered rows; roles: 4 (AirportAdmin/ConcessionAnalyst opaque, Tenant entity_backed:Tenant, Auditor opaque)

**Lint verdict (verbatim):** `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` (410 calls scanned; instance names unique across both design files; forbidden-vocabulary grep clean.)

**Notable design decisions:**
- **Archetype:** ledger reconciliation (MAG-vs-percentage-rent) blended with compliance/audit; **flat topology** (FK references, no nested ownership) and `hierarchical_override` role model — both diversity-prioritized per §0.3.
- **Dual variants on two domains:** settlement PROVISIONAL (unreported months projected at MAG/12) vs FINAL (ACCEPTED only) — 1,470,000 vs 1,200,000 cents on identical data; SPE TTM vs YTD — 289 vs 480 cents/enplanement on identical data.
- **Combinatorial modes:** (a) day-prorated MAG + tiered percentage + nested `max` true-up (pinned literals: mag 853,330 / pct 1,990,000 / true-up 1,136,670); (b) per-event `ceil` rounding of operating-hours penalties (two 30-min shortfalls → 2×25,000, not 25,000).
- **Non-linear machines on two entities:** Lease ACTIVE↔DEFAULTED default/cure cycle; SalesReport SUBMITTED→DISPUTED→SUBMITTED revision loop.
- **Cascades:** depth-3 audit cascade (findings → report ADJUSTED → settlement recalc + PAID reopen → lease arrears) and depth-2 termination cascade (terminate → draws CANCELLED → TI remaining restored).
- **Temporal overlap with two semantics:** premises terms use half-open `[start, end)` with adjacency allowed; operating-hours waivers require a ≥14-day buffer gap.
- **OCC:** single true-race rule `lease-patch-stale-version` on `PATCH /concessions/leases/{id}` (412 ERR_STALE_VERSION); no wall-clock or pseudo-race entries.
- Logical clock drives lease EXPIRED and settlement OVERDUE sweeps; all money integer cents, rates in basis points, `round_half_up` with per-month-round-then-sum order pinned.

## Step 3: Copy Shared Files — 2026-08-13T13:33:00.000Z

Copied `./INSTRUCTION.md` → `tasks/task_1492_airport_concession_program_rent/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-08-13T13:58:00.000Z

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_1492_airport_concession_program_rent/workspace/PRD.md` — 319 lines.

**Section overview:**
- §1 Introduction (2 paragraphs, business-context angle: MAG-vs-percentage tension plus compliance instruments)
- §2 Global Specifications (9 subsections): 2.1 RBAC with per-role identity translation, 2.2 response envelope (byte-identical to canonical block, verified), 2.3 pagination, 2.4 logical clock and sweeps, 2.5 money/basis-points/rounding discipline, 2.6 common properties + immediate consistency, 2.7 the single OCC rule on lease amendment, 2.8 ten-stage validation pipeline, 2.9 continuously reconciled vs snapshot-at-event derived fields
- §3 Business Logic (9 subsections, program-timeline grouping): onboarding/origination → default/cure/termination/remarketing → monthly reporting → annual settlement math → invoicing/payments/voids/arrears → audits → ACDBE reviews → SPE performance → buildout draws/pricing/hours/waivers
- §4 endpoint table (47 rows, 4 columns), §5 error catalogue (34 rows, 2 columns)

**Contract reports:**
- Field coverage: 55/55 entity fields, 44/44 endpoint inputs (incl. `action`, `note`, `findings`, `to_iso8601`, `expected_lease_version`), 4/4 common fields, 6/6 named outputs — 0 missing. PASS
- Rule coverage: all 34 validations expressed with priority ordering (global pipeline in §2.8 plus explicit endpoint-level orderings), 1/1 OCC rule, all 9 state machines' transitions/side effects, all 7 calculations in reconstructible prose, all 34 error IDs in §2/§3 narrative, all 62 state/enum/action values as exact strings. PASS
- §3 path purity: 395 backticked tokens scanned, 0 paths / 0 bare methods / 0 method+path combos. PASS

**Notable writing decisions:**
- *Scattering:* lease economics fields introduced at origination (§3.1) and consumed in settlement math (§3.4); constants embedded with dual rendering (25,000 cents = $250 per commenced hour; 5,000-cent floor; 2,000 bp = 20% example; 12 months, 30 days, 14-day buffer); filter query params handled in §4 intro to keep §3 list-free.
- *Zero-Silence corners transcribed faithfully:* `DISPUTED` reports excluded from the duplicate-period set; lease-ACTIVE gate (`ERR_LEASE_NOT_ACTIVE`) applies to exactly four operations and NOT to report creation; premises-overlap check precedes date-coherence on lease creation; state check precedes OCC check on lease amendment; `INVOICED → OVERDUE` sweep changes no arrears value (updated_at refresh only); voids never re-apply `OVERDUE`; `PAID` reopen only via audit cascade with FINAL semantics; ACDBE cure does not clear `default_reason`; breakpoint/SPE-floor/ACDBE-goal boundary inclusivity stated explicitly; 4-decimal proration weights and per-month-round-before-annual-sum pinning; approve-time draw preconditions map to `ERR_DRAW_STATE_FORBIDS` (create-time deadline maps to `ERR_BUILDOUT_WINDOW_CLOSED`).
- The withheld design files were never opened; a leakage-marker scan confirmed no `test_recipe`/design references in the output.

## Step 5: Generate Unit Tests — 2026-08-13T14:30:00.000Z

Generation complete. Summary:

## Tests emitted

**Queue A (Difficulty)** — 36 tests, 18/18 instances covered at ≥2 tests each:
- dual_variant_calc: `settlement_provisional_vs_final_true_up` (2), `spe_ttm_vs_ytd_divergence` (2)
- combinatorial_formula: `settlement_proration_nested_max` (2), `hours_penalty_per_event_ceil_then_sum` (2)
- non_linear_state_machine: `lease_default_cure_cycle` (2), `sales_report_dispute_resubmit_cycle` (2)
- transitive_cascade: `audit_findings_restate_reports_cascade` (2), `lease_termination_cancels_draws` (2)
- priority_pair_validation_conflict: `report_patch_state_beats_fiscal` (2), `ti_draw_temporal_beats_fiscal` (2)
- boundary_precision_check: `true_up_zero_when_percentage_equals_mag` (2), `acdbe_attainment_exactly_at_goal` (2)
- cross_entity_state_dependency: `report_submit_requires_active_lease` (2), `payment_requires_payable_settlement` (2)
- resource_temporal_overlap: `premises_term_overlap_half_open` (2), `waiver_buffer_gap_rule` (2)
- compensating_invariant: `ti_approve_cancel_conserves_allowance` (2), `payment_post_void_conserves_ledger` (2)

**Queue B (Corner)** — 45 tests: 44/45 non-stub instances covered at 1 test each; the 3 `excluded_because:` stubs not translated (all cross-references verified to resolve: `lease_default_cure_cycle`, `sales_report_dispute_resubmit_cycle`, `audit_findings_restate_reports_cascade`).

## Instances skipped (1)

- `Corner/entities/lease_create_computed_arrears_input_ignored` — **computed-field silence / unique-derivability failure**. The instance asserts that a client-supplied `arrears_cents` in the lease-create payload is "ignored" (201 with computed 0). The PRD enumerates the creation payload and states a new lease is born with `arrears_cents` at zero, but never specifies how the server treats an unexpected computed field in the payload: ignore-with-201 and reject-with-400 (`ERR_INVALID_REQUEST`) are both PRD-consistent. Skipped per the Core rule; no placeholder emitted.

## Relaxations noted

- `tenant_creation_applies_defaults_and_system_fields` and `lease_creation_initializes_computed_counters`: the YAML's `version == 1` assertion was relaxed to "version is an integer" (checked via `assert_tenant`/`assert_lease`) because PRD §2.6 defines version as incrementing per mutation but never pins the initial value — a PRD-only reader could start at 0 or 1. The instances' other assertions (default `acdbe_certified` false, UUID id, DRAFT/arrears 0/ti_remaining == allowance) are verbatim-covered and asserted.

## Files

- `test_helpers/` (all under `/home/ubuntu/github/CodingPRD/tasks/task_1492_airport_concession_program_rent/test_helpers/`): `__init__.py` (barrel), `types.py` (11 entity TypedDicts + status/role enums), `api_client.py` (37 endpoint methods incl. `/_clock/set_current_utc`), `api_errors.py` (34 error IDs, HTTP map registered with the framework), `assertions.py` (11 entity assertions + settlement-ledger and lease-balance invariants), `factories.py` (11 payload factories), `constants.py` (penalty/due-days/buffer constants), `test_users.py` (opaque-role shared headers + mandatory `make_tenant_headers(user_id)` builder for the entity-backed Tenant role), `fixtures.py` (state-progression, settlement-to-INVOICED/PAID lifecycles, report/draw/waiver/audit/review helpers, SPE scenario).
- `test_suite/`: `conftest.py` + `test_01_registration_and_leases.py` … `test_10_performance.py`.

## Stage 2 self-check verdict

PASS. 81 tests collected by pytest; every difficulty instance has exactly ≥2 tags, every non-stub corner instance ≥1 (except the single PRD-filter skip above), all 114 PRD citations verified verbatim against PRD.md by substring grep, every docstring ends with exactly one resolving `Design:` line (C4), no `skip`/`skipif`/`xfail` markers anywhere, and both trees byte-compile.

## Step 6: Generate Implementation — 2026-08-13T14:55:00.000Z

Implementation complete and verified. All files live under `/home/ubuntu/github/CodingPRD/tasks/task_1492_airport_concession_program_rent/workspace/implementation/`.

## Files written

- `start.sh` — executable launcher; guarded `pip install` (no-op once Flask is importable), then `exec python3 app.py` in the foreground
- `requirements.txt` — `flask>=2.2,<4`
- `app.py` — Flask entry point, blueprint registration, `before_request` auth, envelope-wrapped error handlers (404/405/500)
- `db.py` — in-memory `Store` (11 dicts keyed by id, starts **empty**, no seeding), logical clock defaulting to exactly `2026-08-01T00:00:00Z`, UUID minting, common-fields factory (`id`/`created_at`/`updated_at`/`version`), monotonic `_seq` for creation-order sorting
- `errors.py` — `ApiError` + all 34 error-id constants from the catalog
- `response.py` — `{meta: {api_request_id (req_*), api_request_timestamp}, response_type, data}` envelope; list responses add `limit`/`offset`/`total_count`/`has_more` to `meta`
- `middleware.py` — `X-User-ID`/`X-User-Role` auth (401 `ERR_UNAUTHENTICATED`), role gating (403), typed field extractors, strict `YYYY-MM-DD`/`YYYY-MM` validators, tenant-ownership check
- `services/core.py` — all six calculations (tiered monthly percentage rent with inclusive breakpoint and per-month round-half-up; MAG proration with 4-decimal monthly weights; PROVISIONAL vs FINAL settlement variants; SPE TTM/YTD windows; ACDBE attainment; per-violation penalty with ceil-per-hour), derived-field reconcilers (`arrears_cents`, `ti_remaining_cents`), termination/expiry cascades, both clock sweeps, per-request dedup'd `touch()` (version +1, `updated_at` refresh)
- `services/validation.py` — enum check + pagination (defaults 10/0, clamped 1–100)
- `routes/` — 11 modules: tenants, leases, sales_reports, settlements (+payments +void), audits, reviews (ACDBE), draws, violations, waivers, enplanements, clock

## Endpoint count

47 routes — every row of the scaffold/PRD §4 endpoint table, including the nested `POST/GET /concessions/settlements/{id}/payments`, `POST /concessions/payments/{id}/void`, and `POST /_clock/set_current_utc`.

## Logical clock / sweeps

Single in-process clock on the store; `POST /_clock/set_current_utc` (AirportAdmin) parses `to_iso8601`, sets the clock, then runs both sweeps synchronously in the same request: lease expiry (`ACTIVE`/`DEFAULTED` with current date strictly `> term_end_date` → `EXPIRED` + draw/waiver/TI cascades) and settlement overdue (`INVOICED`/`PARTIALLY_PAID`, `due_date` strictly before current date, balance > 0 → `OVERDUE`; lease `updated_at` refresh for the INVOICED case only). All timestamps (created_at/updated_at/submitted_at/api_request_timestamp) read the logical clock — never wall-clock — formatted with 3 fractional digits; `due_date` = clock date + 30 days.

## Verification

Exercised end-to-end across three fresh-boot smoke suites (~100 assertions, all passing): full settlement lifecycle (PROVISIONAL projection math, FINAL invoicing, partial/full payments, void re-derivation without re-applying OVERDUE, sweep re-applying it, audit restatement reopening PAID → PARTIALLY_PAID with arrears recompute), MAG proration with partial months, dispute/resubmit loop and DISPUTED-not-blocking re-filing, lease default/cure/terminate/remarket with cascades and premises-release, OCC `ERR_STALE_VERSION`, waiver 14-day buffer boundaries, ACDBE evaluate/cure with `ERR_CURE_INSUFFICIENT`, SPE TTM-vs-YTD divergence and INSUFFICIENT_DATA, violation penalty math (ceil hours, 2×/min pricing), RBAC and tenant scoping, pagination meta, and validation-pipeline orderings called out in PRD §2.8 (lease-active before report-state on SUBMIT; occupation before date coherence; state before stale-version).

`start.sh` binds `0.0.0.0:$PORT` (default 10000) in the foreground via `exec python3 app.py`, and was boot-verified through `bash start.sh` exactly as the evaluator invokes it; every boot starts from a completely empty in-memory store.

## Step 7: Run Tests and Iterate — 2026-08-13T15:06:00.000Z

Clean 8/8 sweep — all 81 tests pass in every round. Exiting with the summary.

## Summary

**Iterations run:** 2 (sweep 1: 5 deterministic failures in all 8 rounds; fixes applied; sweep 2: 81/81 × 8 rounds, clean).

**Tests deleted:** None. Every failing test asserted behavior verbatim-covered by PRD.md; all failures were repairable artifacts bugs.

**Fixes applied to `test_helpers/`:** None.

**Fixes applied to `test_suite/`:**
- `/home/ubuntu/github/CodingPRD/tasks/task_1492_airport_concession_program_rent/test_suite/test_02_lease_lifecycle.py` — `TestPremisesOccupation._setup_incumbent_lease` referenced a bare `api` name that doesn't exist at module scope (`NameError`), breaking both `test_premises_overlap_one_day_before_end_rejected` and `test_premises_adjacent_term_allowed`. Fixed by importing `api_client` from `test_helpers` (the same session-scoped singleton the `api` fixture returns) and using it inside the helper. The asserted PRD rules (§3.1 half-open premises term-overlap and adjacency) are unchanged.

**Fixes applied to `implementation/`:**
- `/home/ubuntu/github/CodingPRD/tasks/task_1492_airport_concession_program_rent/workspace/implementation/routes/audits.py` — `issue_findings` required each finding's report reference under the key `report_id`, while the test artifacts (both design scaffolds, `test_helpers/types.py` `AuditFinding`, and all of `test_06_audits.py`) uniformly send `sales_report_id`. PRD §3.6 ("The payload is a set of `findings`, each pairing a report reference with the auditor's restated gross amount") is silent on the inner key spelling, and the `sales_report_id` spelling matches the PRD's own naming pattern (`lease_id` for the `/concessions/leases` collection → `sales_report_id` for `/concessions/sales-reports`). The parser now accepts `sales_report_id` (with `report_id` as a fallback alias for tolerance). This unblocked `test_findings_restate_report_and_record_understatement`, `test_findings_reopen_paid_settlement_and_recompute_arrears`, and `test_audit_findings_on_unaccepted_report_returns_error` — whose actual assertions (ADJUSTED cascade, `understatement_cents`, FINAL recalc, PAID→PARTIALLY_PAID reopen, `ERR_AUDIT_FINDING_REPORT_STATE`) are all verbatim PRD §3.6 and now pass.

**Feedback note for doc-generator (Zero-Silence Rule):** PRD §3.6 should name the finding object's report-reference key (e.g., "each finding pairs `sales_report_id` with `restated_gross_sales_cents`") — the current prose ("a report reference") admits both `report_id` and `sales_report_id`, and the two generator sides diverged on it.

## Step 8: Finalize PRD — 2026-08-13T15:12:00.000Z

PRD_FINALIZED.md is written. The diff surfaced exactly one PRD silence requiring a patch; everything else in Step 7 was a pure fixture bug.

**Line counts / delta:** PRD.md 319 lines → PRD_FINALIZED.md 319 lines, 0% delta (one line revised in place).

**Changes:**
- §3.6 — revise — pinned the finding object's payload keys: each finding pairs `sales_report_id` (the report reference, also accepted under the fallback alias `report_id`) with `restated_gross_sales_cents`, replacing the undetermined "a report reference with the auditor's restated gross amount" — `implementation/routes/audits.py:92-95`.

**Step-7 items needing no edit:**
- `test_suite/test_02_lease_lifecycle.py` NameError fix — pure test fixture bug (missing `api_client` import); the asserted §3.1 half-open overlap/adjacency rules were already verbatim in the PRD and unchanged.

**Per-edit pre-edit search log:**
- Edit 1 (§3.6 findings payload keys):
  - (a) Subject: request-payload key spellings of a finding object consumed by `POST /concessions/audits/{id}/issue-findings`.
  - (b) Paths enumerated: grep for `sales_report_id` / `report_id` / `findings` / `restated_gross_sales_cents` across all of `implementation/` found exactly one payload consumer — `issue_findings` in `implementation/routes/audits.py` (lines 76–146): `rid = f.get('sales_report_id')`, fallback `f.get('report_id')`, amount `f.get('restated_gross_sales_cents')`. Other hits are non-payload: `routes/sales_reports.py:67` (stored field initialized to None at report creation) and `services/core.py:81` (stored field read for effective-gross). Verified `routes/sales_reports.py` parses only `lease_id`, `period_month`, `gross_sales_cents`, `action` from bodies — no other endpoint accepts `restated_gross_sales_cents` as input. §4's table row for issue-findings names no keys, so nothing to contradict.
  - (c) Wording adjustment: kept the original sentence structure and "set"; inserted only the key naming plus the alias note. Deliberately did not pin the error mapping for a malformed/negative amount (impl raises `ERR_INVALID_REQUEST` there, but that check was not part of the Step 7 fix and §2.8 stage 4 already covers shape validation generically) — under-determined wording preferred over a claim that could diverge from off-site behavior.

## Step 9: Complete PRD — 2026-08-13T15:40:00.000Z

Done. `PRD_COMPLETED.md` produced as a minimal patch over `PRD_FINALIZED.md` (which itself differed from `PRD.md` only in the findings-payload sentence).

**Volume**: 319 → 321 lines; 47,611 → 51,722 chars (+4,111 chars). 19 diff hunks, all inline inserts/revisions; no new sections, no deletions of pinned behavior.

**Counts**: 21 ambiguity-pins, 3 mismatch-revisions.

**Ambiguity-pins** (PRD silent; pinned to impl):
- §2.2 — insert — framework-level failures on the same error envelope: unknown path → `ERR_NOT_FOUND` 404, unsupported method → `ERR_INVALID_REQUEST` on HTTP 405, unexpected failure → `ERR_INTERNAL` 500 (absent from §5) — app.py:29-39
- §2.3 — revise — `limit`/`offset` out-of-range values are clamped (not rejected); non-integer → `ERR_INVALID_REQUEST` — services/validation.py:26-38
- §2.3 — revise — list ordering is creation (insertion) order, coinciding with ascending creation timestamps unless the clock moved backward — db.py:56 (`_seq`), e.g. routes/leases.py:107
- §2.3 — revise — `has_more` true exactly when items remain beyond the returned page — services/validation.py:45
- §2.4 — insert — every emitted timestamp (`api_request_timestamp`, `created_at`, `updated_at`, `submitted_at`) is rendered from the logical clock — db.py:42-45, response.py:19
- §2.4 — insert — clock-set semantics: any instant allowed (backward too), offset-less read as UTC, unparseable → `ERR_INVALID_REQUEST`, `current_utc` rendered with six fractional digits iff sub-second precision present — routes/clock.py:15-47
- §2.6 — revise — `version` starts at 1 at creation — db.py:56
- §2.8 stage 4 — revise — empty string fails presence; JSON boolean never satisfies an integer field; malformed date/month strings are malformed — middleware.py:31-104
- §3.1 — insert — lease creation applies no sign/positivity validation to economic fields — routes/leases.py:53-60
- §3.1 — revise — lease born with `default_reason` null — routes/leases.py:96
- §3.2 — revise — `reason` mandatory for `DECLARE_DEFAULT` (missing → `ERR_INVALID_REQUEST`), read only for that action — routes/leases.py:176-179
- §3.3 — revise — optional `note` accepted but not persisted — routes/sales_reports.py:124-159
- §3.4 — revise — settlement born with `due_date` null — routes/settlements.py:58
- §3.5 — revise — overdue sweep's lease `updated_at` refresh carries the §2.6 `version` increment — services/core.py:236-238
- §3.6 — revise — audit case born with `understatement_cents` at zero — routes/audits.py:48
- §3.6 — insert — finding-level shape/existence failures (negative/non-integer restated amount → `ERR_INVALID_REQUEST`; unresolved report → `ERR_NOT_FOUND`) surface before the audit-state check — routes/audits.py:82-110
- §3.6 — insert — findings validated atomically before any applied; empty set accepted (→ `FINDINGS_ISSUED`, zero understatement); duplicate findings applied in payload order with per-finding deltas — routes/audits.py:112-130
- §3.6 — revise — "The owning settlement" → "The settlement of each affected year" recalculated (windows may span years) — routes/audits.py:123,137-140
- §3.7 — revise — negative `certified_revenue_cents` / negative cure amount → `ERR_INVALID_REQUEST` (400, not 422) — routes/reviews.py:84-86,116-118
- §3.8 — revise — `sales_ttm_cents`/`enplanements_ttm` reported as zero, never null, when no months qualify — services/core.py:253-264
- §3.9 — insert — violation: active-lease gate precedes kind-specific measure checks; missing/non-integer measure → `ERR_INVALID_REQUEST`; non-positive → `ERR_INVALID_AMOUNT`; inapplicable measure field stored null — routes/violations.py:41-71
- §3.9 — revise — waiver `reason` required (missing/empty → `ERR_INVALID_REQUEST`); active-lease gate precedes date coherence, so failing both surfaces `ERR_LEASE_NOT_ACTIVE` — routes/waivers.py:40-50
- §4 — insert — `status`/`kind` list filters enum-validated (`ERR_INVALID_ENUM`); other filters match literally — routes/leases.py:111-112 and equivalents in all list endpoints

**Mismatch-revisions** (PRD described different behavior):
- §3.4 — revise — "a paid year reopens only through audit findings" → reopens through audit findings or the §3.5 payment-void re-derivation (impl void unconditionally re-derives status, moving `PAID` → `PARTIALLY_PAID`/`INVOICED`) — routes/settlements.py:199-203
- §3.6 — revise — "this reopen is the only way out of `PAID`" → reopen plus payment-void are the only ways — routes/settlements.py:199-206
- §3.7 — revise — "cure_additional_certified_cents — zero until a cure is attempted" → zero until a cure succeeds; a rejected (`ERR_CURE_INSUFFICIENT`) attempt leaves stored figures unchanged — routes/reviews.py:126-131

Everything else in the implementation (47 endpoints, state machines, MAG proration, tiered percentage rent, PROVISIONAL/FINAL variants, arrears/TI reconciliation, penalty formulas, 14-day waiver buffer as `max(gap) ≥ 14`, OCC, sweeps, cascades, role gating) was already uniquely pinned by PRD_FINALIZED.md and left untouched.
