import {
  apiClient,
  buildUserHeaders,
  handleApiResponse,
  validateErrorEnvelope,
  createContractPayload,
  createEventPayload,
  createShiftPayload,
  createStaffProfilePayload,
  createAssignmentPayload,
  StaffingContract,
  Event,
  Shift,
  StaffProfile,
  Assignment,
  UserRole,
  ApiErrorId,
  createUnixTimestamp,
  addHours,
  AssignmentStatus,
  ContractStatus,
  createAndActivateContract
} from '../../../test-helpers';

describe('Phase 4: Edge Cases', () => {
  const coordinatorHeaders = buildUserHeaders('coordinator-1', UserRole.StaffingCoordinator);
  const staffMemberHeaders = buildUserHeaders('staff-1', UserRole.StaffMember);
  const accountManagerHeaders = buildUserHeaders('manager-1', UserRole.AccountManager);

  describe('TCB-12-01: Shift creation with default certification', () => {
    it('should default certification_needed to NONE when omitted and allow assignment', async () => {
      const contract = await createAndActivateContract();
      const event = await apiClient.createEvent(contract.id, createEventPayload(), coordinatorHeaders)
        .then(res => handleApiResponse<Event>(res, 201));
      const staff = await apiClient.createStaffProfile(contract.id, createStaffProfilePayload(), coordinatorHeaders)
        .then(res => handleApiResponse<StaffProfile>(res, 201));

      const shiftPayload = createShiftPayload({ role_name: 'Default Cert Shift' });

      const shiftRes = await apiClient.createShift(contract.id, event.id, shiftPayload, coordinatorHeaders);
      const shift = handleApiResponse<Shift>(shiftRes, 201);

      expect(shift.certification_needed).toBe('NONE');

      const assignmentRes = await apiClient.createAssignment(
        contract.id,
        createAssignmentPayload(shift.id, staff.id),
        accountManagerHeaders
      );
      const assignment = handleApiResponse<Assignment>(assignmentRes, 201);

      expect(assignment.shift_id).toBe(shift.id);
      expect(assignment.staff_profile_id).toBe(staff.id);
    });
  });

  describe('TCB-10-05: Complex rest period validation with mixed assignment states', () => {
    it('should ignore PROPOSED assignments during confirmation rest period check', async () => {
      const contract = await createAndActivateContract();
      const event = await apiClient.createEvent(contract.id, createEventPayload(), coordinatorHeaders)
        .then(res => handleApiResponse<Event>(res, 201));
      const staff = await apiClient.createStaffProfile(contract.id, createStaffProfilePayload(), coordinatorHeaders)
        .then(res => handleApiResponse<StaffProfile>(res, 201));

      const shiftA_start = createUnixTimestamp(24);
      const shiftA_end = addHours(shiftA_start, 8);
      const shiftA = await apiClient.createShift(contract.id, event.id, createShiftPayload({ role_name: 'Shift A', start_time: shiftA_start, end_time: shiftA_end }), coordinatorHeaders)
        .then(res => handleApiResponse<Shift>(res, 201));
      const assignA = await apiClient.createAssignment(contract.id, createAssignmentPayload(shiftA.id, staff.id), accountManagerHeaders)
        .then(res => handleApiResponse<Assignment>(res, 201));
      await apiClient.acceptAssignment(contract.id, assignA.id, staffMemberHeaders);
      await apiClient.confirmAssignment(contract.id, assignA.id, coordinatorHeaders);

      const shiftC_start = createUnixTimestamp(24 * 3);
      const shiftC_end = addHours(shiftC_start, 8);
      const shiftC = await apiClient.createShift(contract.id, event.id, createShiftPayload({ role_name: 'Shift C', start_time: shiftC_start, end_time: shiftC_end }), coordinatorHeaders)
        .then(res => handleApiResponse<Shift>(res, 201));
      const assignC = await apiClient.createAssignment(contract.id, createAssignmentPayload(shiftC.id, staff.id), accountManagerHeaders)
        .then(res => handleApiResponse<Assignment>(res, 201));
      await apiClient.acceptAssignment(contract.id, assignC.id, staffMemberHeaders);

      const shiftB_start = addHours(shiftC_end, 1);
      const shiftB_end = addHours(shiftB_start, 8);
      const shiftB = await apiClient.createShift(contract.id, event.id, createShiftPayload({ role_name: 'Shift B', start_time: shiftB_start, end_time: shiftB_end }), coordinatorHeaders)
        .then(res => handleApiResponse<Shift>(res, 201));
      await apiClient.createAssignment(contract.id, createAssignmentPayload(shiftB.id, staff.id), accountManagerHeaders);

      const confirmRes = await apiClient.confirmAssignment(contract.id, assignC.id, coordinatorHeaders);
      const confirmedAssignmentC = handleApiResponse<Assignment>(confirmRes, 200);

      expect(confirmedAssignmentC.status).toBe(AssignmentStatus.CONFIRMED);
    });
  });

  describe('TCB-7-01: Negative cost difference on confirmation decrements budget', () => {
    it('should correctly decrement provisional_debits when confirmation reduces assignment cost', async () => {
      const contract = await createAndActivateContract(10000.00);
      const event = await apiClient.createEvent(contract.id, createEventPayload(), coordinatorHeaders).then(res => handleApiResponse<Event>(res, 201));
      const staff = await apiClient.createStaffProfile(contract.id, createStaffProfilePayload({ base_pay_rate_per_hour: 20.00 }), coordinatorHeaders).then(res => handleApiResponse<StaffProfile>(res, 201));

      const otherStaff = await apiClient.createStaffProfile(contract.id, createStaffProfilePayload({ first_name: 'Other' }), coordinatorHeaders).then(res => handleApiResponse<StaffProfile>(res, 201));
      const shift41h = await apiClient.createShift(contract.id, event.id, createShiftPayload({ role_name: 'Long Shift', start_time: createUnixTimestamp(1), end_time: addHours(createUnixTimestamp(1), 41) }), coordinatorHeaders).then(res => handleApiResponse<Shift>(res, 201));
      const otherAssign = await apiClient.createAssignment(contract.id, createAssignmentPayload(shift41h.id, otherStaff.id), accountManagerHeaders).then(res => handleApiResponse<Assignment>(res, 201));

      const shift2h = await apiClient.createShift(contract.id, event.id, createShiftPayload({ role_name: 'Short Shift', start_time: createUnixTimestamp(100), end_time: addHours(createUnixTimestamp(100), 2) }), coordinatorHeaders).then(res => handleApiResponse<Shift>(res, 201));
      const mainAssign = await apiClient.createAssignment(contract.id, createAssignmentPayload(shift2h.id, staff.id), accountManagerHeaders).then(res => handleApiResponse<Assignment>(res, 201));

      const contractBeforeAccept = await apiClient.getContract(contract.id, coordinatorHeaders).then(res => handleApiResponse<StaffingContract>(res, 200));
      const budgetBeforeAccept = contractBeforeAccept.budget_balance;

      await apiClient.acceptAssignment(contract.id, mainAssign.id, staffMemberHeaders);

      await apiClient.cancelAssignment(contract.id, otherAssign.id, coordinatorHeaders);

      const provisionalCostWhenProposed = mainAssign.provisional_cost;

      const confirmRes = await apiClient.confirmAssignment(contract.id, mainAssign.id, coordinatorHeaders);
      const confirmedAssign = handleApiResponse<Assignment>(confirmRes, 200);

      const standardCost = 2 * 20.00;
      expect(confirmedAssign.provisional_cost).toBe(standardCost);
      expect(confirmedAssign.is_overtime_eligible).toBe(false);

      const contractAfterConfirm = await apiClient.getContract(contract.id, coordinatorHeaders).then(res => handleApiResponse<StaffingContract>(res, 200));

      const expectedBudget = contract.total_budget - confirmedAssign.provisional_cost;

      expect(contractAfterConfirm.budget_balance).toBeCloseTo(expectedBudget);
    });
  });

  describe('TCB-7-02: Cancelling assignment with override flag but no penalty', () => {
    it('should not decrement risk score if override penalty was not applied', async () => {
      const contract = await createAndActivateContract();
      const event = await apiClient.createEvent(contract.id, createEventPayload(), coordinatorHeaders).then(res => handleApiResponse<Event>(res, 201));
      const staff = await apiClient.createStaffProfile(contract.id, createStaffProfilePayload(), coordinatorHeaders).then(res => handleApiResponse<StaffProfile>(res, 201));
      const shift = await apiClient.createShift(contract.id, event.id, createShiftPayload(), coordinatorHeaders).then(res => handleApiResponse<Shift>(res, 201));

      const assignmentRes = await apiClient.createAssignment(
        contract.id,
        createAssignmentPayload(shift.id, staff.id, { override_risk_check: true }),
        accountManagerHeaders
      );
      const assignment = handleApiResponse<Assignment>(assignmentRes, 201);

      expect(assignment.risk_override_penalty_applied).toBe(false);
      const contractState1 = await apiClient.getContract(contract.id, coordinatorHeaders).then(res => handleApiResponse<StaffingContract>(res, 200));
      expect(contractState1.compliance_risk_score).toBe(0);

      await apiClient.cancelAssignment(contract.id, assignment.id, coordinatorHeaders);

      const contractState2 = await apiClient.getContract(contract.id, coordinatorHeaders).then(res => handleApiResponse<StaffingContract>(res, 200));
      expect(contractState2.compliance_risk_score).toBe(0);
    });
  });

  describe('TCB-93: Failed assignment confirmation due to budget does not alter ledgers', () => {
    it('should return ERR_INSUFFICIENT_BUDGET on confirmation if cost exceeds budget', async () => {
      const contract = await createAndActivateContract(850.00);
      const event = await apiClient.createEvent(contract.id, createEventPayload(), coordinatorHeaders).then(res => handleApiResponse<Event>(res, 201));
      const staff = await apiClient.createStaffProfile(contract.id, createStaffProfilePayload({ base_pay_rate_per_hour: 20.00 }), coordinatorHeaders).then(res => handleApiResponse<StaffProfile>(res, 201));

      const shift1 = await apiClient.createShift(contract.id, event.id, createShiftPayload({ start_time: addHours(createUnixTimestamp(1), 10), end_time: addHours(createUnixTimestamp(1), 51) }), coordinatorHeaders).then(res => handleApiResponse<Shift>(res, 201));
      const shift2 = await apiClient.createShift(contract.id, event.id, createShiftPayload({ start_time: createUnixTimestamp(1), end_time: addHours(createUnixTimestamp(1), 1) }), coordinatorHeaders).then(res => handleApiResponse<Shift>(res, 201));

      const assign1Res = await apiClient.createAssignment(contract.id, createAssignmentPayload(shift1.id, staff.id), accountManagerHeaders).then(res => handleApiResponse<Assignment>(res, 201));
      await apiClient.acceptAssignment(contract.id, assign1Res.id, staffMemberHeaders);
      await apiClient.confirmAssignment(contract.id, assign1Res.id, coordinatorHeaders);

      const assign2Res = await apiClient.createAssignment(contract.id, createAssignmentPayload(shift2.id, staff.id), accountManagerHeaders);
      validateErrorEnvelope(assign2Res, { expectedErrorId: ApiErrorId.ERR_INSUFFICIENT_BUDGET });
    });
  });

  describe('TCB-8-02: Assignment mutations are contract-isolated', () => {
    let contractA: StaffingContract;
    let contractB: StaffingContract;
    let assignmentInA: Assignment;

    beforeEach(async () => {
      contractA = await createAndActivateContract();
      contractB = await createAndActivateContract();
      const eventA = await apiClient.createEvent(contractA.id, createEventPayload(), coordinatorHeaders).then(res => handleApiResponse<Event>(res, 201));
      const staffA = await apiClient.createStaffProfile(contractA.id, createStaffProfilePayload(), coordinatorHeaders).then(res => handleApiResponse<StaffProfile>(res, 201));
      const shiftA = await apiClient.createShift(contractA.id, eventA.id, createShiftPayload(), coordinatorHeaders).then(res => handleApiResponse<Shift>(res, 201));

      const assignmentRes = await apiClient.createAssignment(contractA.id, createAssignmentPayload(shiftA.id, staffA.id), accountManagerHeaders);
      assignmentInA = handleApiResponse<Assignment>(assignmentRes, 201);
    });

    it('should fail to CONFIRM an assignment via the wrong contract path', async () => {
      await apiClient.acceptAssignment(contractA.id, assignmentInA.id, staffMemberHeaders);

      const confirmRes = await apiClient.confirmAssignment(contractB.id, assignmentInA.id, coordinatorHeaders);

      validateErrorEnvelope(confirmRes, { expectedErrorId: ApiErrorId.ERR_ASSIGNMENT_NOT_FOUND });
    });

    it('should fail to CANCEL an assignment via the wrong contract path', async () => {
      const cancelRes = await apiClient.cancelAssignment(contractB.id, assignmentInA.id, coordinatorHeaders);

      validateErrorEnvelope(cancelRes, { expectedErrorId: ApiErrorId.ERR_ASSIGNMENT_NOT_FOUND });
    });
  });

  describe('TCB-8-07 & TCB-8-08: Two-phase costing model (provisional vs. final payout)', () => {
    it('should demonstrate that final_payout can differ from provisional_cost due to chronological payroll calculation', async () => {
      const contract = await createAndActivateContract(10000.00);
      const event = await apiClient.createEvent(contract.id, createEventPayload(), coordinatorHeaders).then(res => handleApiResponse<Event>(res, 201));
      const staff = await apiClient.createStaffProfile(contract.id, createStaffProfilePayload({ base_pay_rate_per_hour: 10.00 }), coordinatorHeaders).then(res => handleApiResponse<StaffProfile>(res, 201));

      const shiftAStart = addHours(createUnixTimestamp(1), 33);
      const shiftA = await apiClient.createShift(
        contract.id,
        event.id,
        createShiftPayload({ start_time: shiftAStart, end_time: addHours(shiftAStart, 25) }),
        coordinatorHeaders
      ).then(res => handleApiResponse<Shift>(res, 201));

      const shiftBStart = createUnixTimestamp(1);
      const shiftB = await apiClient.createShift(
        contract.id,
        event.id,
        createShiftPayload({ start_time: shiftBStart, end_time: addHours(shiftBStart, 25) }),
        coordinatorHeaders
      ).then(res => handleApiResponse<Shift>(res, 201));

      const assignARes = await apiClient.createAssignment(contract.id, createAssignmentPayload(shiftA.id, staff.id), accountManagerHeaders).then(res => handleApiResponse<Assignment>(res, 201));
      await apiClient.acceptAssignment(contract.id, assignARes.id, staffMemberHeaders);
      const confirmedA = await apiClient.confirmAssignment(contract.id, assignARes.id, coordinatorHeaders).then(res => handleApiResponse<Assignment>(res, 200));
      expect(confirmedA.is_overtime_eligible).toBe(false);
      expect(confirmedA.provisional_cost).toBe(250.00);

      const assignBRes = await apiClient.createAssignment(contract.id, createAssignmentPayload(shiftB.id, staff.id), accountManagerHeaders).then(res => handleApiResponse<Assignment>(res, 201));
      await apiClient.acceptAssignment(contract.id, assignBRes.id, staffMemberHeaders);
      const confirmedB = await apiClient.confirmAssignment(contract.id, assignBRes.id, coordinatorHeaders).then(res => handleApiResponse<Assignment>(res, 200));
      expect(confirmedB.is_overtime_eligible).toBe(true);
      expect(confirmedB.provisional_cost).toBeCloseTo(300.00);

      await apiClient.initiatePayroll(contract.id, coordinatorHeaders);
      await apiClient.finalizePayroll(contract.id, coordinatorHeaders);

      const finalA = await apiClient.getAssignment(contract.id, confirmedA.id, coordinatorHeaders).then(res => handleApiResponse<Assignment>(res, 200));
      const finalB = await apiClient.getAssignment(contract.id, confirmedB.id, coordinatorHeaders).then(res => handleApiResponse<Assignment>(res, 200));

      expect(finalA.provisional_cost).not.toBe(finalA.final_payout);

      expect(finalB.final_payout).toBeCloseTo(250.00);
      expect(finalA.final_payout).toBeCloseTo(300.00);
    });
  });
  describe('TCB-4-01: Confirm assignment should not double-count its own hours for OT calculation', () => {
    it('should correctly calculate provisional cost at confirmation without double-counting the confirmed assignment\'s hours', async () => {
      const contract = await createAndActivateContract(5000.00);
      const event = await apiClient.createEvent(contract.id, createEventPayload(), coordinatorHeaders)
        .then(res => handleApiResponse<Event>(res, 201));
      const staff = await apiClient.createStaffProfile(
        contract.id,
        createStaffProfilePayload({ base_pay_rate_per_hour: 20.00 }),
        coordinatorHeaders
      ).then(res => handleApiResponse<StaffProfile>(res, 201));

      const baseShift = await apiClient.createShift(
        contract.id,
        event.id,
        createShiftPayload({ start_time: createUnixTimestamp(24), end_time: addHours(createUnixTimestamp(24), 35) }),
        coordinatorHeaders
      ).then(res => handleApiResponse<Shift>(res, 201));

      const baseAssign = await apiClient.createAssignment(
        contract.id,
        createAssignmentPayload(baseShift.id, staff.id),
        accountManagerHeaders
      ).then(res => handleApiResponse<Assignment>(res, 201));

      await apiClient.acceptAssignment(contract.id, baseAssign.id, staffMemberHeaders);
      await apiClient.confirmAssignment(contract.id, baseAssign.id, coordinatorHeaders);

      const contractAfterBase = await apiClient.getContract(contract.id, coordinatorHeaders).then(res => handleApiResponse<StaffingContract>(res, 200));
      expect(contractAfterBase.budget_balance).toBe(5000.00 - (35 * 20.00));

      const otShift = await apiClient.createShift(
        contract.id,
        event.id,
        createShiftPayload({ start_time: createUnixTimestamp(72), end_time: addHours(createUnixTimestamp(72), 10) }),
        coordinatorHeaders
      ).then(res => handleApiResponse<Shift>(res, 201));

      const otAssign = await apiClient.createAssignment(
        contract.id,
        createAssignmentPayload(otShift.id, staff.id),
        accountManagerHeaders
      ).then(res => handleApiResponse<Assignment>(res, 201));

      expect(otAssign.is_overtime_eligible).toBe(true);
      expect(otAssign.provisional_cost).toBe(250.00);

      await apiClient.acceptAssignment(contract.id, otAssign.id, staffMemberHeaders);

      const confirmRes = await apiClient.confirmAssignment(contract.id, otAssign.id, coordinatorHeaders);
      const confirmedAssignment = handleApiResponse<Assignment>(confirmRes, 200);

      expect(confirmedAssignment.status).toBe(AssignmentStatus.CONFIRMED);
      expect(confirmedAssignment.provisional_cost).toBe(250.00);
      expect(confirmedAssignment.is_overtime_eligible).toBe(true);

      const contractAfterConfirm = await apiClient.getContract(contract.id, coordinatorHeaders).then(res => handleApiResponse<StaffingContract>(res, 200));
      const expectedBudget = 5000.00 - (35 * 20.00) - 250.00;
      expect(contractAfterConfirm.budget_balance).toBe(expectedBudget);
    });
  });

  describe('TCB-16-01: Budget ledger decrements are clamped at zero', () => {
    it('should clamp provisional_debits at zero when a decrement exceeds the current total', async () => {
      const contract = await createAndActivateContract(1000.00);
      const event = await apiClient.createEvent(contract.id, createEventPayload(), coordinatorHeaders).then(res => handleApiResponse<Event>(res, 201));
      const staff = await apiClient.createStaffProfile(contract.id, createStaffProfilePayload({ base_pay_rate_per_hour: 20.00 }), coordinatorHeaders).then(res => handleApiResponse<StaffProfile>(res, 201));

      const shift = await apiClient.createShift(contract.id, event.id, createShiftPayload({ start_time: createUnixTimestamp(24), end_time: addHours(createUnixTimestamp(24), 5) }), coordinatorHeaders)
        .then(res => handleApiResponse<Shift>(res, 201));

      const assignment = await apiClient.createAssignment(contract.id, createAssignmentPayload(shift.id, staff.id), accountManagerHeaders).then(res => handleApiResponse<Assignment>(res, 201));

      const contractState1 = await apiClient.getContract(contract.id, coordinatorHeaders).then(res => handleApiResponse<StaffingContract>(res, 200));
      expect(contractState1.budget_balance).toBe(900.00);

      await apiClient.declineAssignment(contract.id, assignment.id, staffMemberHeaders);
      const contractState2 = await apiClient.getContract(contract.id, coordinatorHeaders).then(res => handleApiResponse<StaffingContract>(res, 200));
      expect(contractState2.budget_balance).toBe(1000.00);

      const declineAgainRes = await apiClient.declineAssignment(contract.id, assignment.id, staffMemberHeaders);
      validateErrorEnvelope(declineAgainRes, { expectedErrorId: ApiErrorId.ERR_ASSIGNMENT_NOT_PROPOSED });

      const finalContractState = await apiClient.getContract(contract.id, coordinatorHeaders).then(res => handleApiResponse<StaffingContract>(res, 200));
      expect(finalContractState.budget_balance).toBe(1000.00);
    });
  });

  describe('Budget Contention and Depletion', () => {
    describe('P4-BUDGET-01.1: Assignment with cost exactly matching remaining budget', () => {
      it('should succeed when assignment cost exactly matches remaining budget', async () => {
        const contractRes = await apiClient.createContract(
          createContractPayload({ total_budget: 100.00 }),
          coordinatorHeaders
        );
        const contract = handleApiResponse<StaffingContract>(contractRes, 201);

        const activateRes = await apiClient.activateContract(contract.id, coordinatorHeaders);
        const activeContract = handleApiResponse<StaffingContract>(activateRes, 200);

        const eventRes = await apiClient.createEvent(
          contract.id,
          createEventPayload({ name: 'Budget Test Event' }),
          coordinatorHeaders
        );
        const event = handleApiResponse<Event>(eventRes, 201);

        const shiftStart = createUnixTimestamp(24);
        const shiftEnd = addHours(shiftStart, 5);
        const shiftRes = await apiClient.createShift(
          contract.id,
          event.id,
          createShiftPayload({
            start_time: shiftStart,
            end_time: shiftEnd,
          }),
          coordinatorHeaders
        );
        const shift = handleApiResponse<Shift>(shiftRes, 201);

        const staffRes = await apiClient.createStaffProfile(
          contract.id,
          createStaffProfilePayload({ base_pay_rate_per_hour: 20.00 }),
          coordinatorHeaders
        );
        const staff = handleApiResponse<StaffProfile>(staffRes, 201);

        const assignmentRes = await apiClient.createAssignment(
          contract.id,
          createAssignmentPayload(shift.id, staff.id),
          accountManagerHeaders
        );
        const assignment = handleApiResponse<Assignment>(assignmentRes, 201);

        expect(assignment.provisional_cost).toBeCloseTo(100.00);

        const contractCheckRes = await apiClient.getContract(contract.id, coordinatorHeaders);
        const updatedContract = handleApiResponse<StaffingContract>(contractCheckRes, 200);
        expect(updatedContract.budget_balance).toBeCloseTo(0.00);
      });
    });

    describe('P4-BUDGET-01.2: Assignment fails when cost is one cent over budget', () => {
      it('should fail when assignment cost exceeds budget by one cent', async () => {
        const contractRes = await apiClient.createContract(
          createContractPayload({ total_budget: 99.99 }),
          coordinatorHeaders
        );
        const contract = handleApiResponse<StaffingContract>(contractRes, 201);

        await apiClient.activateContract(contract.id, coordinatorHeaders);

        const eventRes = await apiClient.createEvent(
          contract.id,
          createEventPayload(),
          coordinatorHeaders
        );
        const event = handleApiResponse<Event>(eventRes, 201);

        const shiftStart = createUnixTimestamp(24);
        const shiftEnd = addHours(shiftStart, 5);
        const shiftRes = await apiClient.createShift(
          contract.id,
          event.id,
          createShiftPayload({
            start_time: shiftStart,
            end_time: shiftEnd,
          }),
          coordinatorHeaders
        );
        const shift = handleApiResponse<Shift>(shiftRes, 201);

        const staffRes = await apiClient.createStaffProfile(
          contract.id,
          createStaffProfilePayload({ base_pay_rate_per_hour: 20.00 }),
          coordinatorHeaders
        );
        const staff = handleApiResponse<StaffProfile>(staffRes, 201);

        const assignmentRes = await apiClient.createAssignment(
          contract.id,
          createAssignmentPayload(shift.id, staff.id),
          accountManagerHeaders
        );

        validateErrorEnvelope(assignmentRes, {
          expectedErrorId: ApiErrorId.ERR_INSUFFICIENT_BUDGET
        });
      });
    });

    describe('P4-BUDGET-02.1: Creating assignment fails if cost exceeds budget due to OT', () => {
      it('should fail to create an assignment if its provisional cost exceeds remaining budget', async () => {
        const contractRes = await apiClient.createContract(
          createContractPayload({ total_budget: 850.00 }),
          coordinatorHeaders
        );
        const contract = handleApiResponse<StaffingContract>(contractRes, 201);

        await apiClient.activateContract(contract.id, coordinatorHeaders);

        const eventRes = await apiClient.createEvent(contract.id, createEventPayload(), coordinatorHeaders);
        const event = handleApiResponse<Event>(eventRes, 201);

        const staffRes = await apiClient.createStaffProfile(
          contract.id,
          createStaffProfilePayload({ base_pay_rate_per_hour: 20.00 }),
          coordinatorHeaders
        );
        const staff = handleApiResponse<StaffProfile>(staffRes, 201);

        const shiftAStart = createUnixTimestamp(24);
        const shiftAEnd = addHours(shiftAStart, 38);
        const shiftARes = await apiClient.createShift(
          contract.id,
          event.id,
          createShiftPayload({ start_time: shiftAStart, end_time: shiftAEnd }),
          coordinatorHeaders
        );
        const shiftA = handleApiResponse<Shift>(shiftARes, 201);

        const assignmentARes = await apiClient.createAssignment(
          contract.id,
          createAssignmentPayload(shiftA.id, staff.id),
          accountManagerHeaders
        );
        const assignmentA = handleApiResponse<Assignment>(assignmentARes, 201);
        await apiClient.acceptAssignment(contract.id, assignmentA.id, staffMemberHeaders);
        await apiClient.confirmAssignment(contract.id, assignmentA.id, coordinatorHeaders);

        const shiftBStart = createUnixTimestamp(72);
        const shiftBEnd = addHours(shiftBStart, 4);
        const shiftBRes = await apiClient.createShift(
          contract.id,
          event.id,
          createShiftPayload({ start_time: shiftBStart, end_time: shiftBEnd }),
          coordinatorHeaders
        );
        const shiftB = handleApiResponse<Shift>(shiftBRes, 201);

        const assignmentBRes = await apiClient.createAssignment(
          contract.id,
          createAssignmentPayload(shiftB.id, staff.id),
          accountManagerHeaders
        );

        validateErrorEnvelope(assignmentBRes, {
          expectedErrorId: ApiErrorId.ERR_INSUFFICIENT_BUDGET
        });

        const contractCheckRes = await apiClient.getContract(contract.id, coordinatorHeaders);
        const updatedContract = handleApiResponse<StaffingContract>(contractCheckRes, 200);
        expect(updatedContract.budget_balance).toBeCloseTo(90.00);
      });
    });

    describe('P4-BUDGET-02.2: Budget freed by declining can be immediately consumed', () => {
      it('should allow new assignment after budget freed by declining', async () => {
        const contractRes = await apiClient.createContract(
          createContractPayload({ total_budget: 100.00 }),
          coordinatorHeaders
        );
        const contract = handleApiResponse<StaffingContract>(contractRes, 201);

        await apiClient.activateContract(contract.id, coordinatorHeaders);

        const eventRes = await apiClient.createEvent(
          contract.id,
          createEventPayload(),
          coordinatorHeaders
        );
        const event = handleApiResponse<Event>(eventRes, 201);

        const staffRes = await apiClient.createStaffProfile(
          contract.id,
          createStaffProfilePayload({ base_pay_rate_per_hour: 20.00 }),
          coordinatorHeaders
        );
        const staff = handleApiResponse<StaffProfile>(staffRes, 201);

        const shiftAStart = createUnixTimestamp(24);
        const shiftAEnd = addHours(shiftAStart, 5);
        const shiftARes = await apiClient.createShift(
          contract.id,
          event.id,
          createShiftPayload({
            role_name: 'Shift A',
            start_time: shiftAStart,
            end_time: shiftAEnd,
          }),
          coordinatorHeaders
        );
        const shiftA = handleApiResponse<Shift>(shiftARes, 201);

        const assignmentARes = await apiClient.createAssignment(
          contract.id,
          createAssignmentPayload(shiftA.id, staff.id),
          accountManagerHeaders
        );
        const assignmentA = handleApiResponse<Assignment>(assignmentARes, 201);

        const shiftBStart = createUnixTimestamp(48);
        const shiftBEnd = addHours(shiftBStart, 5);
        const shiftBRes = await apiClient.createShift(
          contract.id,
          event.id,
          createShiftPayload({
            role_name: 'Shift B',
            start_time: shiftBStart,
            end_time: shiftBEnd,
          }),
          coordinatorHeaders
        );
        const shiftB = handleApiResponse<Shift>(shiftBRes, 201);

        await apiClient.declineAssignment(contract.id, assignmentA.id, staffMemberHeaders);

        const assignmentBRes = await apiClient.createAssignment(
          contract.id,
          createAssignmentPayload(shiftB.id, staff.id),
          accountManagerHeaders
        );
        const assignmentB = handleApiResponse<Assignment>(assignmentBRes, 201);

        expect(assignmentB.provisional_cost).toBeCloseTo(100.00);

        const contractCheckRes = await apiClient.getContract(contract.id, coordinatorHeaders);
        const updatedContract = handleApiResponse<StaffingContract>(contractCheckRes, 200);
        expect(updatedContract.budget_balance).toBeCloseTo(0.00);
      });
    });

    describe('P4-BUDGET-03.1: Assignment creation fails when provisional cost exceeds budget', () => {
      it('should fail to create assignment when provisional cost with overtime exceeds total budget', async () => {
        const contractRes = await apiClient.createContract(
          createContractPayload({ total_budget: 1000.00 }),
          coordinatorHeaders
        );
        const contract = handleApiResponse<StaffingContract>(contractRes, 201);

        await apiClient.activateContract(contract.id, coordinatorHeaders);

        const eventRes = await apiClient.createEvent(
          contract.id,
          createEventPayload(),
          coordinatorHeaders
        );
        const event = handleApiResponse<Event>(eventRes, 201);

        const staffRes = await apiClient.createStaffProfile(
          contract.id,
          createStaffProfilePayload({ base_pay_rate_per_hour: 20.00 }),
          coordinatorHeaders
        );
        const staff = handleApiResponse<StaffProfile>(staffRes, 201);

        const shiftStart = createUnixTimestamp(24);
        const shiftEnd = addHours(shiftStart, 50);
        const shiftRes = await apiClient.createShift(
          contract.id,
          event.id,
          createShiftPayload({
            start_time: shiftStart,
            end_time: shiftEnd,
          }),
          coordinatorHeaders
        );
        const shift = handleApiResponse<Shift>(shiftRes, 201);

        const assignmentRes = await apiClient.createAssignment(
          contract.id,
          createAssignmentPayload(shift.id, staff.id),
          accountManagerHeaders
        );

        validateErrorEnvelope(assignmentRes, {
          expectedErrorId: ApiErrorId.ERR_INSUFFICIENT_BUDGET,
        });
      });
    });

    describe('P4-BUDGET-03.2: Assignment creation fails when OT cost exceeds budget', () => {
      it('should fail to create an assignment if its OT cost exceeds the remaining budget', async () => {

        const contractRes = await apiClient.createContract(
          createContractPayload({ total_budget: 420.00 }),
          coordinatorHeaders
        );
        const contract = handleApiResponse<StaffingContract>(contractRes, 201);
        await apiClient.activateContract(contract.id, coordinatorHeaders);

        const eventRes = await apiClient.createEvent(contract.id, createEventPayload(), coordinatorHeaders);
        const event = handleApiResponse<Event>(eventRes, 201);

        const staffRes = await apiClient.createStaffProfile(
          contract.id,
          createStaffProfilePayload({ base_pay_rate_per_hour: 10.00 }),
          coordinatorHeaders
        );
        const staff = handleApiResponse<StaffProfile>(staffRes, 201);

        const shiftA_start = createUnixTimestamp(24);
        const shiftA_end = addHours(shiftA_start, 40);
        const shiftARes = await apiClient.createShift(
          contract.id,
          event.id,
          createShiftPayload({ role_name: 'Shift A', start_time: shiftA_start, end_time: shiftA_end }),
          coordinatorHeaders
        );
        const shiftA = handleApiResponse<Shift>(shiftARes, 201);

        const shiftB_start = createUnixTimestamp(72);
        const shiftB_end = addHours(shiftB_start, 2);
        const shiftBRes = await apiClient.createShift(
          contract.id,
          event.id,
          createShiftPayload({ role_name: 'Shift B', start_time: shiftB_start, end_time: shiftB_end }),
          coordinatorHeaders
        );
        const shiftB = handleApiResponse<Shift>(shiftBRes, 201);

        const assignARes = await apiClient.createAssignment(
          contract.id,
          createAssignmentPayload(shiftA.id, staff.id),
          accountManagerHeaders
        );
        const assignA = handleApiResponse<Assignment>(assignARes, 201);
        await apiClient.acceptAssignment(contract.id, assignA.id, staffMemberHeaders);
        await apiClient.confirmAssignment(contract.id, assignA.id, coordinatorHeaders);

        const assignBRes = await apiClient.createAssignment(
          contract.id,
          createAssignmentPayload(shiftB.id, staff.id),
          accountManagerHeaders
        );

        validateErrorEnvelope(assignBRes, {
          expectedErrorId: ApiErrorId.ERR_INSUFFICIENT_BUDGET
        });

        const contractCheckRes = await apiClient.getContract(contract.id, coordinatorHeaders);
        const finalContract = handleApiResponse<StaffingContract>(contractCheckRes, 200);
        expect(finalContract.budget_balance).toBeCloseTo(20.00);
      });
    });
  });
});
