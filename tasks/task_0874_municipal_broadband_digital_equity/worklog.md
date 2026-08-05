# Worklog — task_0874_municipal_broadband_digital_equity

## Step 1: Create task directory — 2026-07-28T00:00:00.000Z

Pre-assigned folder used as-is: tasks/task_0874_municipal_broadband_digital_equity/ (workspace/ subdir already present). Step 1 directory scan skipped per orchestrator instructions.

## Step 2: Generate scaffold — 2026-07-28T02:32:00.000Z

All three scaffold artifacts are generated, parse cleanly, pass `scaffold_lint.py` with a clean verdict, and satisfy the cross-file consistency checks (file-split honored, all 9 difficulty rules carry 2 instances, name uniqueness across both design files, and every `excluded_because` stub references a real §1.8 instance).

Generated a fresh Expert-tier scaffold:
- `SCAFFOLD.yaml` (§1.0–§1.7)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (§1.8 — 18 instances, 2 per rule)
- `SCAFFOLD_CORNER_DESIGN.yaml` (§1.9 — 19 active + 6 excluded stubs)

### Counts
- **14 entities**: Grant, ServiceArea, ServicePlan, SubsidyProgram, Subscriber, Subscription, Enrollment, Technician, InstallOrder, Device, OutageEvent, SlaCredit, Invoice, GrantClaim
- **58 endpoints** (flat topology, `api_prefix: "/"`; one filtered-list GET per child covers all FK reverse-reachability; includes `/_clock/set_current_utc` with the mandated 2026-05-01 startup default)
- **10 state machines**, **6 calculations**, **17 validations** (priority-ordered), **30 errors**, **9 roles**, **2 OCC rules**

### Notable design decisions
- **Archetype**: pricing_engine + compliance_audit (BEAD), layers = dual-variant / OCC / cascading side-effects / rate-threshold.
- **Dual-variant calculations across domains**: SLA credit provisional (clock−started) vs final (ended−started) on the Subscription/SlaCredit domain; reported vs verified take-rate on the ServiceArea domain.
- **Combinatorial modes**: invoice_amount (mode a — ≥3 inputs, nested `min`, conditional on enrollment) and grant_claim_reimbursement (mode b — pinned round-each-then-sum, demonstrably 3000 vs 3001).
- **Non-linear state machines on different entities**: Subscription (parallel service × billing axes), Enrollment (cyclic ACTIVE↔RECERT_DUE), InstallOrder (cyclic reschedule self-loop), GrantClaim (branching approve/reject fork).
- **Cascades**: outage-resolve depth-3 (Outage→SlaCredit→Invoice→PAID/billing) and service-area-suspend depth-3 (Area→Subscription→InstallOrder→Device).
- **SoD**: ComplianceAnalyst submits / ComplianceOfficer approves, enforced via `submitted_by` vs `X-User-ID`; FieldTech is `entity_backed:Technician` with an ownership check on install completion.
- **OCC** (only sanctioned write-conflict mechanism): invoice-payment stale version and grant-claim-create stale grant, both 412.
- **Compensating invariants over two conserved quantities**: device inventory count conservation and two-phase grant-funds money conservation (submit commits, reject releases; `award = available + committed + disbursed`).
- **Temporal overlap on two resources with different interval semantics**: technician half-open `[start,end)` adjacency-allowed vs outage closed-interval + 60-min buffer.

Constants verified declared inline: MINUTES_IN_BILLING_PERIOD=43200, OUTAGE_MERGE_BUFFER_MINUTES=60, FEDERAL_SHARE_PCT=33.34, FPL_BASE_CENTS map, CERT_PERIOD_DAYS=365. All three YAML files safe_load cleanly.

## Step 3: Copy shared files — 2026-07-28T02:33:00.000Z

Copied ./INSTRUCTION.md → tasks/task_0874_municipal_broadband_digital_equity/workspace/INSTRUCTION.md.

## Step 4: Generate PRD — 2026-07-28T02:40:00.000Z

Generated workspace/PRD.md (268 lines) for the Municipal Broadband & Digital-Equity Program API.

**Structure:** §1 Introduction; §2 Global Specs (10 subsections: RBAC, response envelope, pagination, common props/consistency, existence-resolution + validation-priority ordering, monetary/rounding, OCC, logical clock, dual-variant take-rate accounting, grant fund-conservation invariant); §3 Business Logic (7 subsections: program config, subscription lifecycle parallel service/billing axes, install+device inventory, enrollment/recert cycle, billing/invoicing, outages/SLA credits dual-variant + 3-level cascade, grant claims/BEAD SoD fork-join+milestone); §4 Endpoint table (58 endpoints, verified); §5 Error catalogue (30 codes).

**Calculations rendered:** invoice_amount (pinned order), dual-variant SLA credit (MINUTES_IN_BILLING_PERIOD=43200), reported/verified take-rate, per-subscriber reimbursement (FEDERAL_SHARE_PCT=33.34, round-then-sum pinned), FPL (5-tier FPL_BASE_CENTS table, CERT_PERIOD_DAYS=365), milestone check. Both OCC rules → ERR_STALE_VERSION 412. Clock endpoint present.

**Hard Contracts all PASS:** field-name coverage (76 identifiers, 0 missing), rule coverage (validation bands 1–10, both OCC, all transitions/cascades/calcs, grant fork/join — 0 missing), §3 path purity (0 path tokens).

**Notable:** Grant CLOSED/MILESTONE_MET have no dedicated endpoints → described narratively (incl. take_rate_floor_pct clawback-at-close). Informational-only fields (match_required_pct, take_rate_floor_pct) named with meaning.

## Step 5: Generate unit tests — 2026-07-28T02:55:00.000Z

Generated test_helpers/ (9 files) + test_suite/ (conftest + 5 domain files). **55 tests total.**
- Queue A (Difficulty): all 18 instances × 2 tests = 36 tests.
- Queue B (Corner): all 19 non-stub instances × 1 test = 19 tests.
Every test carries verbatim PRD citation + exactly one Design: tag; all 55 tags resolve to real design-index name: entries. 6 excluded_because stubs correctly not translated.

**Notable coverage decisions:**
- `payment_on_void_invoice` — recipe passed stale invoice version; under §2.5 ordering OCC (pri 5) would trip before not-payable (pri 9). Test re-reads current version so only payable-state check can fail → isolates ERR_INVOICE_NOT_PAYABLE.
- Priority-conflict tests (state_beats_fiscal, referential_beats_temporal) assert only the winning error (uniquely derivable from §2.5 bands).
- `list_subscriptions_filtered_by_subscriber` — PRD documents only pagination (§2.3), not a subscriber_id filter → asserts pagination envelope in single-sub DB, cites §2.3.
- Temporal-overlap second tests assert distinct facets (half-open adjacency allowed; rejected report/create persists nothing).
Zero skip/xfail markers; clean compile.

## Step 6: Generate implementation — 2026-07-28T02:55:00.000Z

Built workspace/implementation/ (app.py ~1000 lines, requirements.txt=flask, start.sh guarded-pip + exec python3, reads $PORT, binds 0.0.0.0, foreground). 58 @app.route routes covering all PRD §4 rows + /_clock/set_current_utc. In-memory dict-of-dicts keyed by UUID, wiped per boot; nothing seeded; monotonic _seq for created_at ordering. app.py compiles clean.

**Notable design decisions (ambiguities resolved toward PRD literalism):**
- created_at/updated_at/api_request_timestamp use logical clock rendered as three-fractional-digit ...Z; input datetime fields echoed verbatim; purely-computed datetimes (scheduled_end_at, certification_expires_at) rendered canonically — avoids Z→.000Z bug.
- Pagination out-of-range (limit<1 or >100, offset<0) → ERR_VALIDATION.
- activate with non-serviceable area → ERR_INVALID_STATE; subscription/subscriber area mismatch → ERR_VALIDATION (no dedicated code).
- Payment OCC (band 5) checked before ISSUED-payable business rule (band 9).
Cascades, parallel axes, lazy RECERT_DUE flip, cyclic recertify, half-open tech double-booking, outage 60-min buffer all verified via live smoke tests.

## Step 7: Test and iterate to green — 2026-07-28T03:05:00.000Z

**Final state: 8/8 rounds at 55/55** (confirmed on disk). Sweep run as 2 waves of 4 via workspace/sweep.sh (no inline pkill).

**Iterations run:** 2 (baseline sweep + one fix, then confirming sweep).

**Root cause:** `test_final_credit_uses_ended_minus_started` in test_suite/test_01_pricing_calculations.py failed identically in all 8 rounds (not flakiness), asserting status=="APPLIED" but getting PENDING.

**Diagnosis (STEP 2 — test-setup bug, NOT impl):** PRD §3.6 says resolution creates each SLA credit PENDING, then applies it to "that subscription's latest ISSUED invoice," making it APPLIED. The class's shared `_setup_open_outage` inline setup built an active subscription + reported outage but never generated an invoice, so at resolution there was no ISSUED invoice to apply to. The PRD-faithful impl (app.py:1459-1468) correctly leaves the credit PENDING when no ISSUED invoice exists.

**Tests deleted:** none.
**Fixes to test_suite/:** test_01_pricing_calculations.py, TestSlaCreditProvisionalVsFinal._setup_open_outage — added ctx["invoice"] = fx.generate_invoice(...) after activation so an ISSUED invoice exists for the final credit to become APPLIED at resolution. Does not affect sibling provisional test (reads estimated_credit_total_cents at report time = 100) or final-credit amount (360 min → 50 cents).
**Fixes to test_helpers/:** none.
**Fixes to implementation/:** none — implementation was already PRD-faithful.

## Step 8: Finalize PRD — 2026-07-28T03:08:00.000Z

Produced workspace/PRD_FINALIZED.md. **268 vs 268 lines, 0% delta — byte-identical to PRD.md.** No changes: the single Step-7 diff item was a pure test-setup precondition bug (fixture failed to generate an ISSUED invoice), not a PRD silence or impl mismatch. PRD §3.6 already uniquely determines the impl behavior (SLA credit created PENDING, applied to latest ISSUED invoice → APPLIED; stays PENDING when no ISSUED invoice exists — app.py:1435-1476). No implementation change occurred, so nothing to align. (Step 8 not skipped because the skip condition requires 0 test_suite fixes, and there was 1.)

## Step 9: Complete PRD — 2026-07-28T03:12:00.000Z

Produced workspace/PRD_COMPLETED.md from PRD_FINALIZED.md. 268→268 lines, +1,065 chars. **10 ambiguity-pins, 0 mismatch-revisions** (impl is a faithful superset of PRD; several silences pinned in place):
- §2.3 Pagination — created_at ties break by (created_at, _seq) insertion order (app.py:305).
- §2.9 Take-Rate — homes_passed==0 yields 0.00 not a div error (app.py:363,375).
- §3.2 Subscription create — subscriber/area mismatch → ERR_VALIDATION (app.py:817).
- §3.2 Subscription cancel — cancel from SUSPENDED does no void/compensation (app.py:890).
- §3.4 Enrollment FPL — household_size outside 1–5 → ERR_VALIDATION (app.py:1006).
- §3.6 Outage overlap — OPEN outage window = started_at ±60 min inclusive vs new started_at (app.py:1379).
- §3.6 Provisional credit — downtime floored to whole minutes, clamped 0 if started_at future (app.py:1389).
- §3.6 SLA credit apply — credit with no ISSUED invoice stays PENDING, null applied_invoice_id (app.py:1464).
- §3.7 Claim create — invalid claim period → ERR_PERIOD_INVALID (app.py:531).
- §3.3 Install complete — supplied device need only exist, moved to DEPLOYED unconditionally (app.py:1257).

**Note (not a gap):** §3.1 describes an administrative grant close/clawback (ACTIVE/MILESTONE_MET → CLOSED) with no API endpoint (matches PRD-gen's narrative "administrative/system transition" framing); left untouched — not an interpretation ambiguity.

## PIPELINE COMPLETE

All 9 steps done. Final: **55/55 tests pass across all 8 stability-sweep rounds.** Terminal artifact: workspace/PRD_COMPLETED.md. Implementation had 0 fixes during Step 7 (only 1 test-setup fixture fix).


