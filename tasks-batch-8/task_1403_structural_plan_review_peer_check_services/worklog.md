# Worklog — task_1403_structural_plan_review_peer_check_services

## Step 1: Create Task Directory — 2026-08-13T03:51:00.000Z

Task directory `tasks/task_1403_structural_plan_review_peer_check_services/` and its `workspace/` subdirectory were pre-created and pre-assigned by the pipeline dispatcher (Step 1 treated as DONE; no index scan performed, no other task_* directory touched).

## Step 2: Generate Scaffold — 2026-08-13T04:55:00.000Z

Scaffold for task 1403 generated and lint-clean. All three artifacts are in `/home/ubuntu/github/CodingPRD/tasks/task_1403_structural_plan_review_peer_check_services/`.

**What was generated**

- `SCAFFOLD.yaml` (§1.0–§1.7 only, no design keys): 9 entities (Jurisdiction, Reviewer, Engagement, ReviewCycle, ReviewAssignment, DeficiencyComment, CommentResponse, DeferredSubmittal, ReviewRecord), 6 state machines, 8 calculations, 10 validation priority layers, 38 endpoints (incl. `POST /_clock/set_current_utc` with the mandated 2026-08-01T00:00:00Z default), 41 error codes, 5 roles.
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml`: 18 instances, exactly 2 per rule across all 9 Difficulty Rules, each with structured `setup_api_calls`/`trigger` chains and literal-computed asserts (all fee/date math executed in Python before pinning).
- `SCAFFOLD_CORNER_DESIGN.yaml`: 59 instances (54 active + 5 `excluded_because` stubs) across all nine claim-extraction-guide sections.

**Lint verdict (verbatim)**: `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` (582 calls scanned, 0 violations.)

**Notable design decisions**

- **Archetype blend**: Compliance/audit (seal + responsible-charge + segregation of duties) primary, multi-party negotiation secondary — the comment response cycle is a genuine cyclic negotiation: DeficiencyComment runs OPEN→ADDRESSED→REOPENED→ADDRESSED→VERIFIED, and Engagement loops IN_PROGRESS↔APPROVED via revision cycles (blocked once the record is SEALED).
- **Version-pinning**: engagements snapshot nine jurisdiction rule fields (`pinned_*`) at registration; code-edition citation validation (`ERR_CODE_EDITION_MISMATCH`) checks against the pin, not the live jurisdiction — tested across a jurisdiction update.
- **Two dual-variant calculation domains**: fiscal (estimated fee at registration vs final fee at seal, diverging via actual cycle count and amended valuation) and temporal (BUSINESS vs CALENDAR turnaround, pinned day-counting rules producing different `due_at` for identical inputs).
- **Pinned rounding order** (Rule 2 mode b): per-deferred-item fee rounds `round_half_up(scoped_base × 0.05)` per item then sums — observably 1 cent apart from sum-then-round in the pinned test (366667 vs 366666).
- **One OCC concurrency rule** (`assignment-create-stale-cycle`): assignment creation legitimately supersedes an ACTIVE assignment, passing §1.2.1's serial-observability filter; guarded by `expected_cycle_version` → 412.
- **Segregation of duties**: a ChiefReviewer who is the engagement's reviewer of record cannot waive its comments (`ERR_WAIVER_SEGREGATION_VIOLATION`); CRITICAL comments are never waiverable.
- **Response-window semantics**: comment responses are gated on the engagement's *current* non-terminal cycle being COMMENTS_ISSUED (not the raising cycle), which keeps the reopen loop reachable after supersede — this was caught and fixed during chain replay.
- Mid-run incident: a regex-based bulk edit truncated the first difficulty file; it was rewritten from scratch and both design files re-verified (name uniqueness, error-catalog coverage, RBAC closure, enum closure all mechanically checked — all pass).

## Step 3: Copy Shared Files — 2026-08-13T04:56:00.000Z

Copied `./INSTRUCTION.md` → `tasks/task_1403_structural_plan_review_peer_check_services/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-08-13T05:05:00.000Z

PRD generated at `/home/ubuntu/github/CodingPRD/tasks/task_1403_structural_plan_review_peer_check_services/workspace/PRD.md`. The two withheld design indices were not opened or referenced.

## PRD structure

- **§1 Introduction** — 2 paragraphs (regulatory/business context angle, no template opener)
- **§2 Global Specifications** — 10 subsections: 2.1 RBAC + per-role identity semantics, 2.2 API Response Structure (byte-identical to canonical block, verified by diff), 2.3 Pagination, 2.4 Request Validation Pipeline (10 layers in explicit priority order with masking rule), 2.5 Common Resource Properties (incl. the `CommentResponse` no-`updated_at`/no-`version` exception), 2.6 Pinned Jurisdiction Rule Snapshots, 2.7 Monetary Precision and Rounding (integer cents, round half up at two pinned steps), 2.8 Logical Clock (default `2026-08-01T00:00:00Z`), 2.9 OCC on Cycle Assignment, 2.10 Licensing and Segregation of Duties
- **§3 Business Logic & Workflows** — 8 subsections organized by process timeline: 3.1 firm setup (jurisdictions/reviewers), 3.2 engagement registration/amendment + estimated fee, 3.3 review cycles/supersession/turnaround SLA, 3.4 assignments + capacity, 3.5 comments/responses/waiver, 3.6 deferred submittals, 3.7 approval/record/final fee, 3.8 cancellation
- **§4 Endpoint Definitions** — 4-column table, 38 rows (matches scaffold)
- **§5 Error Code Catalogue** — 2-column table, 41 rows (matches scaffold); document ends here, no audit footer

**Size:** 283 lines, 5,835 words.

## Hard Contract Reports

```
Field coverage check:
- entities[].fields + endpoints input/query/path params: 83 required, 83 present, 0 missing
Status: PASS
```

```
Rule coverage check:
- validations[] with priority: 10 layers expressed in explicit ordered prose (§2.4), 0 missing
- concurrency_rules[] OCC: 1/1 expressed — POST /plan-review/assignments + expected_cycle_version + ERR_STALE_CYCLE_VERSION (412), no race framing
- state_machines[].transitions: 27 checked (6 machines), all from/to states, preconditions with error IDs, and side effects expressed, 0 missing
- calculations[]: 8/8 (estimated_fee, final_fee, turnaround_sla, on_time_evaluation, reviewer_active_load, unresolved_comment_count, deferred_pending_count, cycle_numbering) in precise prose with all constants embedded, 0 missing
- validations[] conditions: all matchable to error IDs in §2/§3 prose, 0 missing
- endpoints[].side_effects / applies_to: all expressed in workflow narrative, 0 missing
- entities[].fields[] structured content (defaults, null-until, computed): reconstructible from prose, 0 missing
- sibling-branch symmetry (waive ×3, cancel ×2, cycle-cancel ×3, response ×2, submit ×2, verify/reopen, approve/reject deferred): equal density, 0 asymmetric
Status: PASS
```

```
Path purity check (§3 only):
- backtick tokens scanned: 405
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

Additional verifications: all 41 error IDs appear in §1–§4 prose (not only in the §5 table); all 20 state enumeration values covered; all enum values (`IBC_2018/2021/2024`, `ASCE7_16/22`, fee methods, SLA modes, building types, risk categories, scopes, severities, categories, item types, `PE`/`SE`) present as exact strings; §2.2 confirmed byte-identical to the canonical source file.

## Step 5: Generate Unit Tests — 2026-08-13T05:30:00.000Z

Generation complete. Summary:

## Test counts

**Total: 89 tests** across 6 files (36 queue A + 53 queue B), plus 9 helpers + conftest.

| File | Tests | Queue A | Queue B |
|---|---|---|---|
| test_01_setup_registry_and_envelope.py | 13 | 0 | 13 |
| test_02_fees.py | 8 | 6 | 2 |
| test_03_cycles_turnaround.py | 11 | 6 | 5 |
| test_04_assignments_capacity.py | 12 | 6 | 6 |
| test_05_comments_workflow.py | 19 | 6 | 13 |
| test_06_records_seal_transmit.py | 26 | 12 | 14 |

## Stage 1 (`test_helpers/`)
`types.py` (9 entities, 6 status enums; `CommentResponse` correctly omits `updated_at`/`version` per common_fields=false), `api_client.py` (all 38 endpoints incl. `/_clock/set_current_utc`), `api_errors.py` (41 errors, registered with `set_error_http_status_map`), `assertions.py` (per-entity + `assert_timestamp_equals` normalizer), `factories.py`, `constants.py` (fee tiers/rates/scope multipliers from PRD §3.2/§3.7), `test_users.py` (opaque shared constants + per-instance `make_reviewer_headers`/`make_chief_reviewer_headers`/`make_applicant_headers` for entity-backed/ownership-gated roles), `fixtures.py` (5-tier composites: `setup_registered_engagement` → `setup_in_review_cycle` → `setup_comments_issued` → `setup_approved_engagement` → `setup_sealed_record`, plus cycle/comment/deferred primitives).

## Coverage audit
- Queue A: all 18 difficulty instances × 2 tests = 36 ✓
- Queue B: 53 of 54 non-stub instances ✓; all 5 `excluded_because` stubs left untranslated and their `difficulty_instance` pointers verified to resolve.

## Skipped instance (1, with reason)
- **`Corner/state_machines/approve_from_open_cycle_rejected`** — PRD-first filter failure (unique derivability). Approving an OPEN cycle with no assignment violates both layer 6 (no ACTIVE assignment to match `X-User-ID` → `ERR_NOT_ASSIGNED_REVIEWER`) and layer 7 (`ERR_CYCLE_NOT_IN_REVIEW`); PRD §2.4's fixed layer order does not say whether the layer-6 identity check "fails" or is vacuous when no assignment exists, so two faithful PRD-only implementers could return different error_ids. Gap left as a gap; no weakened/one-of test emitted.

## Deviations noted
- `deferred_fee_per_item_rounding_then_sum`: the YAML's recipe input (`declared_valuation_cents: 111111000`) contradicts its own pinned asserts (it yields base 705555, not 555555). The test uses `81111000` — the unique valuation that produces the instance's asserted `scoped_base=333333` under the PRD formula — preserving the pre-computed expected values 333333 / 366667 and the per-item-vs-sum 1-cent discrimination.
- Version-literal asserts (`version == 1`, `== 2`) were replaced with captured-value arithmetic (`== stale_version + 1`) or dropped, since PRD §2.5 never pins the initial version value; same for the `updated_at`-advance sub-assertion in the consistency test (logical clock is frozen, so no advance is derivable).

## Self-check results
- Stage 1: all helper modules import cleanly; framework signatures (`validate_error`, `validate_paginated`, `build_user_headers`, `set_error_http_status_map` from `.validators`) verified against the installed `prd_bench_local_runner`.
- Stage 2: all 6 test modules compile and import-execute; every one of the 89 tests carries exactly one `Design:` tag resolving to a real instance; every docstring citation contains a ≥8-word substring that survives a literal whitespace-normalized grep of `workspace/PRD.md` (0 bad citations after fixing 3); no `skip`/`skipif`/`xfail` markers; no scaffold/section references in generated comments.

## Step 6: Generate Implementation — 2026-08-13T05:30:00.000Z

Everything works. Implementation complete and verified.

## Summary

Complete Python + Flask implementation for task_1403 (Structural Plan Review & Peer Check Services), generated in `/home/ubuntu/github/CodingPRD/tasks/task_1403_structural_plan_review_peer_check_services/workspace/implementation/`.

### File tree
```
implementation/
├── start.sh                  # guarded pip install + exec python3 app.py (foreground)
├── requirements.txt          # flask>=3.0.0
├── app.py                    # Flask entry, ApiError handler, blueprint registration
├── db.py                     # in-memory stores (empty dicts), logical clock, serialization
├── errors.py                 # ApiError + all 41 error-ID constants
├── response.py               # meta/response_type/data envelope, list envelope with pagination meta
├── middleware.py             # X-User-ID/X-User-Role auth, RBAC, body/pagination validation
├── routes/
│   ├── jurisdictions.py      # POST/GET/PUT jurisdictions
│   ├── reviewers.py          # POST/GET reviewers
│   ├── engagements.py        # POST/GET list/GET/PUT/cancel engagements
│   ├── cycles.py             # POST/GET list/GET/issue-comments/approve cycles
│   ├── assignments.py        # POST (OCC)/GET list/GET/release assignments
│   ├── comments.py           # POST/GET list/GET comments + responses/verify/reopen/waive
│   ├── deferred.py           # POST/GET list/GET/submit/approve/reject deferred submittals
│   ├── records.py            # GET list/GET/seal/transmit records
│   └── clock.py              # POST /_clock/set_current_utc
└── services/
    ├── fees.py               # estimated/final fee tiers, turnaround SLA
    └── core.py               # aggregates, cascades, license helpers, assignment-ending
```

### Endpoint count
38 endpoints — the full scaffold §1.5 table including `POST /_clock/set_current_utc`.

### State machines implemented (6)
- **Engagement**: REGISTERED → IN_PROGRESS (first cycle) / CANCELLED; IN_PROGRESS → APPROVED (cycle approve cascade) / CANCELLED; APPROVED → IN_PROGRESS (revision, blocked when record sealed) / COMPLETED (transmit cascade)
- **ReviewCycle**: OPEN → IN_REVIEW (first assignment) / CANCELLED; IN_REVIEW → COMMENTS_ISSUED / APPROVED / CANCELLED; COMMENTS_ISSUED → SUPERSEDED (new cycle) / CANCELLED — with completed_at/is_on_time stamped at completion and assignment cascades (COMPLETED on approve/supersede, RELEASED on cancel)
- **ReviewAssignment**: ACTIVE → COMPLETED / RELEASED (incl. reassignment supersede on OCC-guarded create)
- **DeficiencyComment**: OPEN/REOPENED → ADDRESSED (applicant response); ADDRESSED → VERIFIED / REOPENED (current-cycle reviewer); OPEN/ADDRESSED/REOPENED → WAIVED (ChiefReviewer with CRITICAL bar + segregation-of-duties)
- **DeferredSubmittal**: REGISTERED/REJECTED → SUBMITTED; SUBMITTED → APPROVED / REJECTED (reviewer of record only)
- **ReviewRecord**: DRAFT → SEALED → TRANSMITTED, with record auto-create/refresh on engagement approval

### Calculations implemented (8)
- **estimated_fee** — valuation tiers (1% / 0.75% / 0.5%) or per-sqft rates, $500 min base, scope multiplier, round-half-up at the two pinned steps (scoped_base, then expedite on the rounded scoped_base) using `Decimal`; never recomputed
- **final_fee** — same base on current (amended) inputs + resubmittal component (75,000 cents × cycles beyond pinned free allowance) + per-item deferred fee (5% of scoped base, rounded per-item then summed); computed at seal
- **turnaround_sla** — expedite halves day count first (ceil), then CALENDAR (N×24h) or BUSINESS (skip Sat/Sun, land at 23:59:59.999Z, received day never counted)
- **on_time_evaluation** — `completed_at <= due_at` (tie counts on time)
- **reviewer_active_load**, **unresolved_comment_count**, **deferred_pending_count** — aggregate counts with inclusive capacity boundary (rejects at count == max) and exact-zero gates for approval/seal
- **cycle_numbering** — 1-based monotonic per engagement, never reused
- **OCC** on `POST /plan-review/assignments` via `expected_cycle_version` (412 ERR_STALE_CYCLE_VERSION, checked at the state layer before business validations)

### Validation pipeline
All 10 layers in priority order (auth headers → role → body shape → pagination → existence → ownership → state/OCC → regulatory/licensing → business constraints → referential completeness), using the exact error IDs and HTTP statuses from the scaffold (400/403/404/409/412/422).

### start.sh / PORT / 0.0.0.0 / foreground
`start.sh` is `set -euo pipefail`, `cd`s to its own directory, guards dependency install behind `python3 -c "import flask"` (no-op on per-test reboots), and `exec python3 app.py` so the server stays in the foreground with signal propagation. `app.py` binds `host="0.0.0.0"` on `int(os.environ.get("PORT", "10000"))`. Verified: `bash start.sh` boots and serves within seconds; a full process restart wipes all state (empty stores, clock back to 2026-08-01T00:00:00Z, previously-used state_code re-registrable) — matching the per-test-server isolation contract. 86 end-to-end assertions across two smoke suites all pass.

## Step 7: Run Tests and Iterate — 2026-08-13T05:56:00.000Z

All 8 rounds are green: 89/89 in every round, 712/712 total test executions. Exit criteria met.

## Summary

**Iterations run:** 2 (two 8-round parallel sweeps; 16 round-runs total).

**Tests deleted:** none — every failing execution traced to infrastructure, not to a PRD-silent or non-uniquely-derivable assertion.

**Fixes applied to `test_helpers/`:** none. Audited fixtures/factories/role-header builders against PRD §2.1, §3 — all identity mappings (per-reviewer headers for ownership-gated calls, `applicant_contact_id` threading, distinct chief vs. reviewer-of-record) are PRD-faithful. No fixture bug found.

**Fixes applied to `implementation/`:** 1
- `/home/ubuntu/github/CodingPRD/tasks/task_1403_structural_plan_review_peer_check_services/workspace/implementation/start.sh` — replaced the per-restart `python3 -c "import flask"` dependency probe (a full interpreter + Flask import, ~300ms) with `python3 -c "import importlib.util...find_spec('flask')"` (~30ms, no module execution). Rationale: the runner restarts the server before every test (712 restarts per sweep); halving warm boot time (~0.56s → ~0.3s) shrinks exposure to the plugin's 15s restart-poll timeout under host contention. No behavior change; pip install still runs when flask is genuinely absent (verified boot after edit).

**Failure analysis (iteration 1):** 6 non-passing executions across rounds 2, 3, 4, 5, 6, 8 — all clustered inside a single ~8-second window (05:31:07–05:31:15) and all infrastructure-level, zero assertion failures:
- 4× setup errors "API server could not be restarted" (server boot exceeded the plugin's 15s poll during a cross-pipeline load storm — the shared host had 11 concurrent port-registry holders, i.e., ~3 other prd-bench pipelines spawning `python3 -c "import flask, waitress"` checks and `lsof` /proc scans concurrently; kernel logs show no OOM).
- 2× `ConnectionResetError(104)` mid-test (rounds 2, 5): server process died between request write and response read during the same contention event. Tracebacks show fresh connections (Werkzeug already sends `Connection: close`, ruling out a stale keep-alive pool), so no client-side fix was applicable or applied.

**Diagnostic-protocol outcome:** every one of the 89 tests executed assertions that passed in at least one round, and after the boot-latency fix all 712 executions passed — no PRD-coverage gaps (STEP 1), no test-vs-PRD inconsistencies (STEP 2), and no implementation rule bugs (STEP 3) were found. The single fix targeted restart-path latency only, which was the empirically identified flake amplifier.

## Step 8: Finalize PRD — 2026-08-13T06:00:00.000Z

## Summary

**Outcome: zero edits.** `/home/ubuntu/github/CodingPRD/tasks/task_1403_structural_plan_review_peer_check_services/workspace/PRD_FINALIZED.md` is a byte-identical copy of `PRD.md` (verified with `cmp`).

**Line counts and delta:**
- PRD.md: 282 lines
- PRD_FINALIZED.md: 282 lines
- Delta: 0 lines, 0.0%

**Changes:** none — no insert or revise bullets to report.

**Why the single Step 7 fix induces no PRD edit:**

The only `<step_7_diff>` item is the `start.sh` probe swap: `python3 -c "import flask"` → `python3 -c "import importlib.util...find_spec('flask')"` (`implementation/start.sh:9`). Both branches of that conditional produce identical externally observable behavior in every case:
- flask present → skip `pip install` → `exec python3 app.py`
- flask absent → `pip install -q -r requirements.txt` → `exec python3 app.py`

No endpoint, field, state transition, calculation, error code, validation rule, or timing guarantee changed. The fix only reduced launcher-internal detection latency (~300ms → ~30ms) to avoid the test runner's restart-poll timeout under host contention — an infrastructure detail, not an API-visible behavioral choice.

**Pre-edit search log (mandatory, applied to the one candidate edit subject):**
- (a) Subject: startup dependency probing / launcher boot behavior.
- (b) Impl paths enumerated: read `implementation/start.sh` in full (13 lines — the entire launcher); repo-wide grep across `implementation/` (`*.py`, `*.sh`, excluding `__pycache__`) for `find_spec|import flask|pip install` confirmed the probe exists only at `start.sh:9-10` and is referenced nowhere else — `app.py`, `db.py`, `middleware.py`, `errors.py`, `response.py`, `routes/`, `services/` contain no probe logic. Also grepped `PRD.md` for `\bstart\.sh\b|\bpip\b|\bflask\b|\bfind_spec\b|\bboot\b|\blauncher\b` — zero matches; PRD.md is silent on the entire launcher/startup subject (its domain is endpoints, entities, state machines, fee/turnaround calculations, validation pipeline, error catalog, RBAC, and the logical clock).
- (c) Wording adjustment: none needed — since the PRD makes no claim about the subject anywhere and the before/after behavior is externally identical, the correct action is to add nothing. Inserting wording here would itself violate the NO-NEW-MISMATCH rule by pinning an infra detail the PRD deliberately leaves open (the `start.sh` contract belongs to INSTRUCTION.md, not the behavioral PRD), and any such sentence would risk over-constraining launcher behavior the implementation does not uniquely determine.

Per Step 7's diagnostic outcome — 712/712 executions passing after the boot-latency fix, with no PRD-coverage gaps, test-vs-PRD inconsistencies, or implementation rule bugs found — a fresh implementer reading `PRD.md` alone already produces a behaviorally equivalent codebase. Byte-identical copy is the correct output.

## Step 9: Complete PRD Scan — 2026-08-13T06:10:00.000Z

PRD_COMPLETED.md written at `/home/ubuntu/github/CodingPRD/tasks/task_1403_structural_plan_review_peer_check_services/workspace/PRD_COMPLETED.md`.

## Summary

**Source/delta:** `PRD_FINALIZED.md` 282 lines / 44,628 chars → `PRD_COMPLETED.md` 284 lines / 47,376 chars (+2 lines, +2,748 chars). All changes are inline inserts/revisions; no new sections.

**Counts:** 15 ambiguity-pins, 1 mismatch-revision (16 edits total).

**Changes:**

- §2.1 — insert — ambiguity — whitespace-only header values count as empty (`ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`) — implementation/middleware.py:20
- §2.1 — insert — ambiguity — unrecognized role strings rejected with `ERR_INSUFFICIENT_PERMISSIONS` — middleware.py:13,32
- §2.2 — insert — ambiguity — undefined routes, unsupported methods, and unexpected failures answered with `ERR_INVALID_REQUEST` / HTTP 400 in the standard envelope — implementation/app.py:37-47
- §2.3 — insert — ambiguity — non-integer `limit`/`offset` rejected with `ERR_INVALID_PAGINATION_PARAMETERS` — middleware.py:124-135
- §2.3 — insert — ambiguity — list sort tie-break by `id` ascending; `has_more` = `offset` + page size < `total_count` — implementation/response.py:35, routes list sorts
- §2.4 layer 3 — insert — ambiguity — undeclared body fields rejected (`ERR_INVALID_REQUEST`); no-field action endpoints ignore any body; explicit null treated as omitted on PUT partial updates — middleware.py:61-64, routes/engagements.py:158-163, routes/jurisdictions.py:96-111
- §2.4 layer 5 — insert — ambiguity — added `raised_in_cycle_id` to the body identifier existence list — routes/comments.py:66-68
- §2.4 layer 6 — revise — mismatch — carved out verify/reopen: their `ERR_NO_ACTIVE_REVIEW_CYCLE` state check precedes the assigned-reviewer identity check (impl evaluates state before ownership here, contrary to the strict layer order) — routes/comments.py:193-197
- §2.5 — insert — ambiguity — `version` starts at 1 at creation — implementation/db.py:75
- §2.8 — insert — ambiguity — timezone-naive `to_iso8601` read as UTC; unparseable value rejected with `ERR_INVALID_REQUEST` — routes/clock.py:15-27
- §3.1 — insert — ambiguity — malformed `state_code` (not exactly two uppercase letters) is `ERR_INVALID_REQUEST` — routes/jurisdictions.py:46-47
- §3.1 — insert — ambiguity — license entry missing a field, bad `license_type`, or unparseable `expires_on` rejected with `ERR_INVALID_REQUEST` — routes/reviewers.py:56-62
- §3.3 — insert — ambiguity — new cycle born `OPEN` with `load_path_confirmed`/`lateral_system_confirmed` both false — routes/cycles.py:105-106
- §3.5 — insert — ambiguity — verify/reopen check firing order pinned: `ERR_NO_ACTIVE_REVIEW_CYCLE` → `ERR_NOT_ASSIGNED_REVIEWER` → `ERR_COMMENT_NOT_ADDRESSED` — routes/comments.py:193-200
- §3.5 — insert — ambiguity — waiving a `VERIFIED`/already-`WAIVED` comment rejected with `ERR_INVALID_REQUEST`; waiver checks fire state → CRITICAL bar → segregation — routes/comments.py:246-256
- §3.6 — insert — ambiguity — deferred submit from a status other than `REGISTERED`/`REJECTED`, and approve/reject on a non-`SUBMITTED` item, rejected with `ERR_INVALID_STATE_TRANSITION`; item born with `rejection_reason` null — routes/deferred.py:71,120-122,145-147,171-173
- §3.7 — insert — ambiguity — `record_number` zero-padding pinned to (at least) two digits, e.g. `RR-WA-03` — routes/cycles.py:224-226
- §4 preamble — insert — ambiguity — per-endpoint returned-resource convention (cycle/comment/submittal/record/assignment/engagement actions return the path-named resource; response posting returns the new `CommentResponse`; clock returns `{current_utc}`) — all routes files

**Verification notes:** Fees (tiers, per-sqft rates, $500 floor, scope factors, two pinned round-half-up steps, resubmittal/deferred components), turnaround computation (expedite ceil-halving before mode, BUSINESS day skipping, 23:59:59.999Z landing), OCC on assignment creation, all state machines, cascade effects, error catalogue (42 codes with statuses), and §4 role columns were all checked against implementation and already matched — no revisions needed there.
