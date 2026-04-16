# Performance Analysis: workspace_opus_4.7_xhigh_effort_ep01

**Result: 125/131 (95.4%) — 5 failed, 1 skipped**

No dominant root cause: failures are five independent contract/semantics defects, not a cascade. Implementation is overwhelmingly correct — auth, RBAC, envelopes, CRUD, vaccination compliance, home-visit flow, application workflow, fee computation, capacity accounting, and most state transitions all pass.

## Root Causes

### 1. `BoardingReservation.nights` not serialized — 1 failure

`create_reservation` (app.py:1232) computes `nights` as a local variable to validate and price the reservation, but never stores it on the record and omits it from `serialize_reservation` (app.py:343–357). The assertion helper requires `isinstance(data["nights"], int) and data["nights"] >= 1` on every reservation response, so the first field access raises `KeyError`. The PRD lists `nights` as a derived response attribute of the reservation resource; the model treated it as a purely internal computation.

### 2. `HomeVisit.yard_verified` initialized to `None` instead of `False` — 1 failure

`schedule_home_visit` (app.py:852) sets `yard_verified: None` on creation and `serialize_home_visit` returns it verbatim. The assertion `isinstance(data.get("yard_verified", False), bool)` — which only defaults when the key is absent — sees `None`, a non-bool, and fails `test_reviewer_schedules_visit`. Either the boolean must default to `False` at creation or the key must be omitted until the inspector submits.

### 3. `Adopter.home_visit_status` not cascaded on FAILED submission — 1 failure

`submit_home_visit` with `safety_score < 70` (app.py:913–923) flips the *home visit* to `FAILED` and cascades application rejections, but never touches `adopter.home_visit_status`, which stays `PENDING`. The PASS branch correctly writes `PASSED` and `home_visit_expires_at` (app.py:910–912). Symmetry was broken on the failure branch.

### 4. `approve` race reports wrong error code for the loser — 1 failure

Under `LOCK`, the first `approve_application` transitions the animal to `HELD` and cascades sibling applications to `REJECTED` with `last_error='ERR_ANIMAL_ALREADY_RESERVED'` (app.py:1099–1105). By the time the second approver runs, the sibling is already in `REJECTED`, so the state guard at app.py:1066 returns `ERR_INVALID_STATE` before the `animal_has_active_holder` check at app.py:1088 can emit the PRD-mandated `ERR_ANIMAL_ALREADY_RESERVED`. Error-precedence inversion: the cascade-rejection side effect masks the concurrency-contract error.

### 5. `capture`/`refund` race produces two successes — 1 failure

Global `LOCK` serializes the two operations. Capture flips `PENDING → COMPLETED`; refund then legally matches its `status == 'COMPLETED'` guard (app.py:1514) and flips to `REFUNDED`, so both return 200. PRD §2.8 treats the pair as racing on the initial `PENDING` state — exactly one should transition; the loser must see `ERR_INVALID_STATE`. The implementation lacks that "starting-state snapshot" semantic; its lock provides mutual exclusion but not the required first-writer-wins gate.

## Model Weaknesses

**Incomplete state-machine symmetry.** The model correctly implemented the PASSED branch of home-visit submission but forgot to mirror the FAILED branch's effect on the parent entity. Branches of a transition tend to be co-located in the PRD but easy to skip when coding one path at a time.

**Derived fields treated as ephemeral.** `nights` was computed to serve pricing and validation but never promoted into the persisted/serialized shape. The model does not consistently cross-check every field named in the PRD's entity tables against its serializer outputs.

**Optional-boolean initialization.** Using `None` as a placeholder for not-yet-set booleans defeats `isinstance(..., bool)` checks that are common in black-box contracts. The model defaulted to SQL-style nullability instead of the PRD's "present-and-typed" convention.

**Lock-as-concurrency-contract conflation.** The model assumed a process-wide `threading.Lock` is sufficient for all §2.8 concurrency guarantees. For approve-race and capture/refund-race, the *error-code* and *which-operation-wins* contracts are about the initial state, not serialization order — the implementation needs to snapshot pre-state and enforce precedence, which a coarse lock alone cannot express.

## What Passed

All envelope/auth/RBAC/pagination tests, both shelter and animal CRUD including OCC, the entire vaccination compliance suite, adopter registration and home-visit scheduling precondition checks, the full approval pipeline (preconditions, side effects, sibling cascade, fee pinning), all fee-calculation boundary cases including senior-discount rounding, reservation pricing/quote/check-in/check-out/cancel, settlement create/capture/refund happy paths, finalize and its cascades, and one of three concurrency tests (capacity race). The correct parts cover ~95% of the surface; the remaining defects are concentrated at two edges — derived-field surfacing and race-condition semantics.
