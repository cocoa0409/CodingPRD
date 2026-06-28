# Worklog — task_0665_mobile_mechanic_onsite_repair

## Step 1: Create Task Directory — 2026-06-26T18:18:36.000Z

Directory `tasks/task_0665_mobile_mechanic_onsite_repair/` and `workspace/` already existed (pre-created by parallel-run harness). Step 1 directory-scan skipped per execution directives. Using folder verbatim as {task_dir}. Confirmed root `INSTRUCTION.md` present.

## Step 2: Generate Scaffold — 2026-06-26T18:37:00.000Z

All structural requirements are satisfied. The scaffold is complete and passes the lint cleanly.

Generated all three scaffold artifacts for **task_0665_mobile_mechanic_onsite_repair** (Mobile Mechanic & On-Site Auto Repair, YourMechanic/Wrench style) at **Expert** difficulty, purely from the scenario description and the skill specification (no sibling tasks consulted). `scaffold_lint.py` returns **VERDICT: clean lint** (476 calls scanned, all FKs reverse-reachable).

**Complexity profile**: primary archetype `workflow_orchestration` + secondary `pricing_engine`; flat topology; branching state-machine shape; peer-roles model; immediate consistency. Layers: cascading side effects, dual-variant calculation, optimistic concurrency, resource temporal-overlap, version-pinning on approval.

**SCAFFOLD.yaml** (§1.0–§1.7):
- **11 entities**: Customer, FleetAccount, Mechanic, ServiceRequest, Quote, JobVisit, PartLine, CatalogPart (common_fields:false / immutable), InspectionFinding, Payment, WarrantyClaim.
- **5 state machines** with non-linear shapes: ServiceRequest (branching ON_SITE/TOW + pre-dispatch cancel), JobVisit (parallel work dimension + abort compensation), Quote (revision cycle SENT↔REVISION_REQUESTED), WarrantyClaim (revision cycle UNDER_REVIEW↔INFO_REQUESTED), Payment (settle/refund). Plus **2 concurrency rules** (OCC on ServiceRequest.version for quote-approve and dispatch).
- **4 calculations**: `part_line_markup` (marginal tiered, round-per-unit), `quote_estimate_total` (forward-looking, dual variants estimate/final), `final_job_total` (aggregation, sum-hours-then-round), `fleet_credit_headroom` (threshold, inclusive `<=`, at_approval vs at_invoice variants).
- **16 validations** (priority-ordered), **15 errors**, **5 roles** (Customer/Mechanic/FleetManager entity_backed; Dispatcher/PlatformAdmin opaque).
- **52 endpoints** (incl. `/_clock/set_current_utc` with default 2026-04-01T00:00:00Z, and added filtered-list/sub-resource GETs for FK reverse-reachability).

**SCAFFOLD_DIFFICULTY_DESIGN.yaml**: **18 instances** = 9 rules × 2, all literal-pinned.

**SCAFFOLD_CORNER_DESIGN.yaml**: **36 instances** across all 9 claim-extraction sections (31 active + 5 `excluded_because:` stubs).

## Step 3: Copy Shared Files — 2026-06-26T18:37:00.000Z

Copied root `INSTRUCTION.md` → `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-06-26T18:42:00.000Z

Generated PRD at `workspace/PRD.md` (285 lines).

**Sections covered:**
- **§1 Introduction** — 2 paragraphs framing the mobile-mechanic domain and its core estimate-vs-final-bill tension.
- **§2 Global Specifications** (11 subsections): 2.1 RBAC with all five roles and every `identity:` translated; 2.2 fixed verbatim response envelope; 2.3 Pagination; 2.4 Common Resource Properties (CatalogPart flagged `common_fields:false` — id/created_at only); 2.5 Nested Retrieval/path validation; 2.6 Zones/Territory; 2.7 Precision/round-half-up; 2.8 Cascading side effects & compensation; 2.9 Fleet Credit Ledger invariant; 2.10 Validation ordering; 2.11 OCC.
- **§3 Business Logic** (10 lifecycle-organized subsections): seeding, intake/quote conversation, estimate pricing, dispatch fork, visit work dimension, parts/findings/add-ons, fleet headroom, payment/warranty, tiered parts markup, final-bill reconstruction.
- **§4** 4-column endpoint table (all 53 endpoints); **§5** 2-column error table (all 16 errors).

**Hard Contracts — all PASS:** Field-Name Coverage (57 required identifiers, 0 missing); Rule Coverage (all state transitions, both OCC rules with `expected_service_request_version`+`ERR_STALE_VERSION`/412, all four calculations, all 16 validations matched to error IDs with priority ordering, cascading side effects & compensations); §3 Path Purity (282 backtick tokens, 0 violations). Numeric constants embedded (markup bands 5000/20000/15000 cents @ 45/30/18 pct, 30-day warranty window, 30-min callback buffer, clock default 2026-04-01T00:00:00Z).

**Confirmation:** Did NOT read SCAFFOLD_DIFFICULTY_DESIGN.yaml or SCAFFOLD_CORNER_DESIGN.yaml.

## Step 7: Run Tests and Iterate — 2026-06-26T19:33:00.000Z

All 8 rounds pass 65/65. Clean sweep. Exiting with the summary.

**Iterations run:** 2 sweeps (initial diagnostic sweep at 64/66; final verification sweep at 65/65).

**Tests deleted (1):**
- `test_finish_with_unresolved_finding_rejected` (in `test_suite/test_05_addons_and_finish.py`) — **ERROR PRECEDENCE SILENCE**. The test asserts `finish` returns `ERR_ADDONS_UNRESOLVED` (409) when a PROPOSED finding remains. But PRD §3.6 states "the first proposed finding drives the request `IN_PROGRESS → AWAITING_ADDON_APPROVAL`", so any request carrying a PROPOSED finding is in `AWAITING_ADDON_APPROVAL`, never `IN_PROGRESS`. PRD §1's explicit priority order places the state check (`ERR_INVALID_STATE`, priority 5) before domain rules including "add-on resolution". A faithful PRD-only implementer therefore returns `ERR_INVALID_STATE` (the implementation does exactly this), and the `ERR_ADDONS_UNRESOLVED` finish branch is unreachable. The PRD does not support the "IN_PROGRESS + PROPOSED" reading that would make `ERR_ADDONS_UNRESOLVED` possible, so even the `validate_error_is_one_of([...])` relaxation is not warranted — deletion required. Scaffold rule that drove the test: `Difficulty/boundary_precision_check/finish_with_unresolved_findings_empty_set_edge`.

**Fixes applied to test_suite/ (1):**
- `test_suite/test_05_addons_and_finish.py`, `test_resolve_addons_omits_proposed_finding_returns_validation_pending` — **STEP 2 test bug (setup inconsistent with PRD).** The setup created TWO PROPOSED findings via two `add_finding` calls; the second call necessarily failed with `ERR_INVALID_STATE` because PRD §3.6 only permits recording a finding while `IN_PROGRESS`, and the first finding had already moved the request to `AWAITING_ADDON_APPROVAL`. A request can hold at most one PROPOSED finding at a time. Rewrote the setup to record a single PROPOSED finding and submit an empty `decisions` list, which omits that one proposed finding and so still faithfully exercises the verbatim exact-cover rule ("no proposed finding may be omitted... rejected with `ERR_VALIDATION_PENDING` (HTTP 422)"). The assertion (`ERR_VALIDATION_PENDING`, 422) was preserved unchanged.

**Fixes applied to test_helpers/:** none.

**Fixes applied to implementation/:** none. The implementation was already PRD-faithful in both relevant paths (finish's priority-ordered state check before the add-ons check; resolve-addons' exact-cover rejection of an empty/omitting decisions list). Storage confirmed in-memory only (Python dicts in `db.store.*`); `routes/seeding.py` is misnamed but contains only on-demand POST creation endpoints and the clock setter — no startup seeding, no cardinal-rule violation.

**Final per-round counts:** round 1: 65/65, round 2: 65/65, round 3: 65/65, round 4: 65/65, round 5: 65/65, round 6: 65/65, round 7: 65/65, round 8: 65/65 — all 8 parallel rounds passed==total.

## Step 8: Finalize PRD — 2026-06-26T19:35:00.000Z

Step 8 ran (NOT skipped — Step 7 made 1 test deletion + 1 test_suite fix, so the 0-of-all-four skip condition did not hold). Outcome: `PRD_FINALIZED.md` created as a verbatim copy of `PRD.md` (285 lines each, byte-identical, 0.0% delta). **Zero edits.**

Both Step 7 diff items were evaluated and neither revealed a genuine PRD silence/mismatch vs. implementation/:
- **Diff item 1 (test deletion `test_finish_with_unresolved_finding_rejected`)** — NOT a PRD silence. PRD §3.6 (line 177) verbatim: "the first proposed finding drives the request `IN_PROGRESS → AWAITING_ADDON_APPROVAL`"; PRD §2.10 (line 121) places the `ERR_INVALID_STATE` state precondition before all domain rules. Impl (`routes/job_visits.py:109-110` then `:117-120`) returns `ERR_INVALID_STATE` first, exactly as PRD dictates; the `ERR_ADDONS_UNRESOLVED` finish branch is unreachable. Pure test bug.
- **Diff item 2 (test setup fix, single-PROPOSED invariant + empty decisions → `ERR_VALIDATION_PENDING`)** — NOT a PRD silence. The one-PROPOSED-at-a-time invariant follows from PRD §3.6 line 177 verbatim; the omitting-decisions rejection is PRD §3.6 line 179 verbatim ("no proposed finding may be omitted ... rejected with `ERR_VALIDATION_PENDING` (HTTP 422)"). Impl matches at `routes/service_requests.py:270-285` and `:335-346`. Pure fixture bug.

Mandatory pre-edit enumeration was still performed (subject: PROPOSED-finding lifecycle, AWAITING_ADDON_APPROVAL transitions, ERR_ADDONS_UNRESOLVED vs ERR_VALIDATION_PENDING precedence; paths read: `routes/job_visits.py` finish/abort, `routes/service_requests.py` record_finding/resolve_addons/cancel/send_quote, `errors.py`, `services/models.py:152`) before concluding zero edits. Out-of-scope observation (not edited, HARD SCOPE): `resolve_addons` adds a duplicate-`finding_id` → `ERR_VALIDATION_PENDING` check (`service_requests.py:339-340`) not spelled verbatim in PRD but arguably subsumed by the exact-cover rule.

## Step 9: Complete PRD — 2026-06-26T19:38:00.000Z

Produced `workspace/PRD_COMPLETED.md` (started from `PRD_FINALIZED.md`). Full PRD-vs-implementation/ scan. Line counts unchanged (285 → 285); char delta **+1,965** (44,600 → 46,565) — all edits inline within existing paragraphs/list items, no new sections.

**Counts:** ambiguity-pins: 5, mismatch-revisions: 1 (plus one additional warranty-window upper-bound clarification folded into §3.8).

**Per-change:**
- `§2.2 (api_request_timestamp)` — insert — ambiguity — Pinned `api_request_timestamp` is the server **wall clock**, distinct from the logical clock driving resource timestamps — `response.py:15-17`.
- `§2.2 (data field)` — insert — ambiguity — Pinned which single primary resource is returned when one operation mutates several (send-quote→quote, approve/reject/revision→quote, dispatch→job visit, record-finding→finding, resolve-addons→service request, depart/start/finish/abort→job visit, settle/refund→payment, warranty actions→claim, clock→empty object) — `quotes.py:74`, `job_visits.py:93,169`, `service_requests.py:215,371`, `warranty_claims.py:136`, `seeding.py:26`.
- `§2.3 (Pagination)` — insert — ambiguity — Pinned out-of-range / non-integer `limit`/`offset` are **clamped or defaulted, not rejected** (limit→[1,100], offset→≥0, unparseable→default) — `middleware.py:34-61`.
- `§2.4 (Common Resource Properties)` — insert — ambiguity — Pinned `created_at`/`updated_at` are stamped from the **logical clock**, not wall clock — `services/models.py:9-21` via `db.now_iso`.
- `§2.11 (OCC)` — insert — ambiguity — Pinned the stale-version check runs **after** the other domain rules: after headroom+suspension for approve, after zone+skill+overlap for dispatch — `quotes.py:57-67`, `service_requests.py:194-205`.
- `§3.2 (Intake — severity)` — revise — mismatch — PRD claimed an `EMERGENCY` request "ranks ahead of a `ROUTINE` one during dispatch selection," but `severity` is only stored, never used for selection/ordering; dispatch targets an explicitly-named `mechanic_id`. Revised to state severity is advisory and drives no automated selection/ordering — `service_requests.py:54-57`, `services/models.py:82` (no consumer anywhere).
- `§3.8 (Warranty window)` — insert — ambiguity — Made explicit that the completion instant for the window comparison is the request's `updated_at` at approval time and only the upper bound (≤30 days) is enforced — `warranty_claims.py` approve path.

**Notable behaviors checked, left unchanged (PRD already pins correctly):** finish does not re-check fleet suspension (PRD scopes suspension to approvals/settlements); approve uses `quoted_total_cents` == `estimate_total_cents`; Customer/FleetManager ownership on payments/settle covered by §2.1 general descendant rule; validation priority ordering NOT_FOUND → INVALID_STATE → INVALID_REQUEST matches §2.10.

**Pipeline complete** — `workspace/PRD_COMPLETED.md` exists on disk.
