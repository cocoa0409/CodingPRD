import {
  apiClient,
  buildUserHeaders,
  handleApiResponse,
  validateErrorEnvelope,
  createContractPayload,
  createEventPayload,
  createShiftPayload,
  createStaffProfilePayload,
  createAssignmentPayload, StaffingContract,
  Event,
  Shift,
  StaffProfile,
  Assignment, EventStatus,
  UserRole,
  ApiErrorId,
  createUnixTimestamp,
  addHours,
  createAndActivateContract,
  CertificationType,
  AssignmentStatus
} from '../../../test-helpers';

describe('Phase 4: Edge Cases', () => {
  const coordinatorHeaders = buildUserHeaders('coordinator-1', UserRole.StaffingCoordinator);
  const accountManagerHeaders = buildUserHeaders('manager-1', UserRole.AccountManager);
  const staffMemberHeaders = buildUserHeaders('staff-1', UserRole.StaffMember);

  describe('Compliance Risk Lock and Ledger Manipulation', () => {
    describe('P4-RISK-02.1: Cancelling assignment with override correctly decrements score', () => {
      it('should decrement score by both OT and override penalties when cancelling', async () => {
        const contractRes = await apiClient.createContract(
          createContractPayload({ total_budget: 10000.00 }),
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

        for (let i = 0; i < 3; i++) {
          const staffRes = await apiClient.createStaffProfile(
            contract.id,
            createStaffProfilePayload({
              first_name: `Staff${i}`,
              last_name: 'Member',
              base_pay_rate_per_hour: 20.00
            }),
            coordinatorHeaders
          );
          const staff = handleApiResponse<StaffProfile>(staffRes, 201);

          const baseStart = createUnixTimestamp(i * 100);
          const baseEnd = addHours(baseStart, 40);
          const baseShiftRes = await apiClient.createShift(
            contract.id,
            event.id,
            createShiftPayload({
              start_time: baseStart,
              end_time: baseEnd,
            }),
            coordinatorHeaders
          );
          const baseShift = handleApiResponse<Shift>(baseShiftRes, 201);

          const baseAssignRes = await apiClient.createAssignment(
            contract.id,
            createAssignmentPayload(baseShift.id, staff.id),
            accountManagerHeaders
          );
          const baseAssign = handleApiResponse<Assignment>(baseAssignRes, 201);
          await apiClient.acceptAssignment(contract.id, baseAssign.id, staffMemberHeaders);
          await apiClient.confirmAssignment(contract.id, baseAssign.id, coordinatorHeaders);

          const otStart = createUnixTimestamp(i * 100 + 50);
          const otEnd = addHours(otStart, 5);
          const otShiftRes = await apiClient.createShift(
            contract.id,
            event.id,
            createShiftPayload({
              start_time: otStart,
              end_time: otEnd,
            }),
            coordinatorHeaders
          );
          const otShift = handleApiResponse<Shift>(otShiftRes, 201);

          const otAssignRes = await apiClient.createAssignment(
            contract.id,
            createAssignmentPayload(otShift.id, staff.id),
            accountManagerHeaders
          );
          const otAssign = handleApiResponse<Assignment>(otAssignRes, 201);
          await apiClient.acceptAssignment(contract.id, otAssign.id, staffMemberHeaders);
          await apiClient.confirmAssignment(contract.id, otAssign.id, coordinatorHeaders);
        }

        const mainStaffRes = await apiClient.createStaffProfile(
          contract.id,
          createStaffProfilePayload({
            first_name: 'Main',
            last_name: 'Staff',
            base_pay_rate_per_hour: 20.00
          }),
          coordinatorHeaders
        );
        const mainStaff = handleApiResponse<StaffProfile>(mainStaffRes, 201);

        const mainBaseStart = createUnixTimestamp(400);
        const mainBaseEnd = addHours(mainBaseStart, 40);
        const mainBaseShiftRes = await apiClient.createShift(
          contract.id,
          event.id,
          createShiftPayload({
            start_time: mainBaseStart,
            end_time: mainBaseEnd,
          }),
          coordinatorHeaders
        );
        const mainBaseShift = handleApiResponse<Shift>(mainBaseShiftRes, 201);

        const mainBaseAssignRes = await apiClient.createAssignment(
          contract.id,
          createAssignmentPayload(mainBaseShift.id, mainStaff.id),
          accountManagerHeaders
        );
        const mainBaseAssign = handleApiResponse<Assignment>(mainBaseAssignRes, 201);
        await apiClient.acceptAssignment(contract.id, mainBaseAssign.id, staffMemberHeaders);
        await apiClient.confirmAssignment(contract.id, mainBaseAssign.id, coordinatorHeaders);

        const otShiftStart = createUnixTimestamp(500);
        const otShiftEnd = addHours(otShiftStart, 1);
        const otShiftRes = await apiClient.createShift(
          contract.id,
          event.id,
          createShiftPayload({
            start_time: otShiftStart,
            end_time: otShiftEnd,
          }),
          coordinatorHeaders
        );
        const otShift = handleApiResponse<Shift>(otShiftRes, 201);

        const assignmentRes = await apiClient.createAssignment(
          contract.id,
          createAssignmentPayload(otShift.id, mainStaff.id, {
            override_risk_check: true
          }),
          accountManagerHeaders
        );
        const assignment = handleApiResponse<Assignment>(assignmentRes, 201);

        const intermediateCheckRes = await apiClient.getContract(contract.id, coordinatorHeaders);
        const intermediateContract = handleApiResponse<StaffingContract>(intermediateCheckRes, 200);
        expect(intermediateContract.compliance_risk_score).toBe(30);
        const budgetBeforeCancel = intermediateContract.budget_balance;

        await apiClient.cancelAssignment(
          contract.id,
          assignment.id,
          coordinatorHeaders
        );

        const finalCheckRes = await apiClient.getContract(contract.id, coordinatorHeaders);
        const finalContract = handleApiResponse<StaffingContract>(finalCheckRes, 200);
        expect(finalContract.compliance_risk_score).toBe(15);
        expect(finalContract.budget_balance).toBeCloseTo(budgetBeforeCancel + assignment.provisional_cost);
      });
    });

    describe('P4-RISK-02.2: Override penalty persists even when assignment changes from OT to non-OT', () => {
      it('should retain override penalty when assignment changes from overtime to regular on confirmation', async () => {
        const contractRes = await apiClient.createContract(
          createContractPayload({ total_budget: 30000.00 }),
          coordinatorHeaders
        );
        const contract = handleApiResponse<StaffingContract>(contractRes, 201);
        await apiClient.activateContract(contract.id, coordinatorHeaders);
        const eventRes = await apiClient.createEvent(contract.id, createEventPayload(), coordinatorHeaders);
        const event = handleApiResponse<Event>(eventRes, 201);

        for (let i = 0; i < 3; i++) {
          const staffRes = await apiClient.createStaffProfile(contract.id, createStaffProfilePayload({ first_name: `Setup_Staff_${i}` }), coordinatorHeaders);
          const staff = handleApiResponse<StaffProfile>(staffRes, 201);
          const baseStart = createUnixTimestamp(i * 100);
          const baseEnd = addHours(baseStart, 41);
          const baseShiftRes = await apiClient.createShift(contract.id, event.id, createShiftPayload({ start_time: baseStart, end_time: baseEnd }), coordinatorHeaders);
          const baseShift = handleApiResponse<Shift>(baseShiftRes, 201);
          const baseAssignRes = await apiClient.createAssignment(contract.id, createAssignmentPayload(baseShift.id, staff.id), accountManagerHeaders);
          const baseAssign = handleApiResponse<Assignment>(baseAssignRes, 201);
          await apiClient.acceptAssignment(contract.id, baseAssign.id, staffMemberHeaders);
          await apiClient.confirmAssignment(contract.id, baseAssign.id, coordinatorHeaders);
        }

        const staffARes = await apiClient.createStaffProfile(contract.id, createStaffProfilePayload({ first_name: 'Staff', last_name: 'A' }), coordinatorHeaders);
        const staffA = handleApiResponse<StaffProfile>(staffARes, 201);

        const shiftP1Start = createUnixTimestamp(400);
        const shiftP1End = addHours(shiftP1Start, 40);
        const shiftP1Res = await apiClient.createShift(contract.id, event.id, createShiftPayload({ role_name: 'Shift P1', start_time: shiftP1Start, end_time: shiftP1End }), coordinatorHeaders);
        const shiftP1 = handleApiResponse<Shift>(shiftP1Res, 201);
        const assignP1Res = await apiClient.createAssignment(contract.id, createAssignmentPayload(shiftP1.id, staffA.id), accountManagerHeaders);
        const assignP1 = handleApiResponse<Assignment>(assignP1Res, 201);

        const shiftP2Start = createUnixTimestamp(500);
        const shiftP2End = addHours(shiftP2Start, 5);
        const shiftP2Res = await apiClient.createShift(contract.id, event.id, createShiftPayload({ role_name: 'Shift P2', start_time: shiftP2Start, end_time: shiftP2End }), coordinatorHeaders);
        const shiftP2 = handleApiResponse<Shift>(shiftP2Res, 201);
        const assignP2Res = await apiClient.createAssignment(contract.id, createAssignmentPayload(shiftP2.id, staffA.id, {
          override_risk_check: true
        }), accountManagerHeaders);
        const assignP2 = handleApiResponse<Assignment>(assignP2Res, 201);
        await apiClient.acceptAssignment(contract.id, assignP2.id, staffMemberHeaders);

        const contractAt30Res = await apiClient.getContract(contract.id, coordinatorHeaders);
        expect(handleApiResponse<StaffingContract>(contractAt30Res, 200).compliance_risk_score).toBe(30);

        await apiClient.declineAssignment(contract.id, assignP1.id, staffMemberHeaders);

        await apiClient.confirmAssignment(contract.id, assignP2.id, coordinatorHeaders);

        const contractAfterConfirmRes = await apiClient.getContract(contract.id, coordinatorHeaders);
        expect(handleApiResponse<StaffingContract>(contractAfterConfirmRes, 200).compliance_risk_score).toBe(25);

        const staffBRes = await apiClient.createStaffProfile(contract.id, createStaffProfilePayload({ first_name: 'Staff', last_name: 'B' }), coordinatorHeaders);
        const staffB = handleApiResponse<StaffProfile>(staffBRes, 201);

        const staffBBaseStart = createUnixTimestamp(600);
        const staffBBaseEnd = addHours(staffBBaseStart, 40);
        const staffBBaseShiftRes = await apiClient.createShift(contract.id, event.id, createShiftPayload({ role_name: 'Staff B Base', start_time: staffBBaseStart, end_time: staffBBaseEnd }), coordinatorHeaders);
        const staffBBaseShift = handleApiResponse<Shift>(staffBBaseShiftRes, 201);
        const staffBBaseAssignRes = await apiClient.createAssignment(contract.id, createAssignmentPayload(staffBBaseShift.id, staffB.id), accountManagerHeaders);
        const staffBBaseAssign = handleApiResponse<Assignment>(staffBBaseAssignRes, 201);
        await apiClient.acceptAssignment(contract.id, staffBBaseAssign.id, staffMemberHeaders);
        await apiClient.confirmAssignment(contract.id, staffBBaseAssign.id, coordinatorHeaders);

        const shiftB_OT_start = createUnixTimestamp(700);
        const shiftB_OT_end = addHours(shiftB_OT_start, 1);
        const shiftB_OT_Res = await apiClient.createShift(contract.id, event.id, createShiftPayload({ role_name: 'Shift B OT', start_time: shiftB_OT_start, end_time: shiftB_OT_end }), coordinatorHeaders);
        const shiftB_OT = handleApiResponse<Shift>(shiftB_OT_Res, 201);

        const assignB_OT_Res = await apiClient.createAssignment(
          contract.id,
          createAssignmentPayload(shiftB_OT.id, staffB.id),
          accountManagerHeaders
        );

        validateErrorEnvelope(assignB_OT_Res, { expectedErrorId: ApiErrorId.ERR_RISK_THRESHOLD_EXCEEDED });

        const finalContractRes = await apiClient.getContract(contract.id, coordinatorHeaders);
        expect(handleApiResponse<StaffingContract>(finalContractRes, 200).compliance_risk_score).toBe(25);
      });
    });

    describe('P4-RISK-02.3: Risk score decrement is clamped at zero', () => {
      it('should clamp risk score at zero when decrementing', async () => {
        const contractRes = await apiClient.createContract(
          createContractPayload({ total_budget: 5000.00 }),
          coordinatorHeaders
        );
        const contract = handleApiResponse<StaffingContract>(contractRes, 201);
        await apiClient.activateContract(contract.id, coordinatorHeaders);
        const eventRes = await apiClient.createEvent(contract.id, createEventPayload(), coordinatorHeaders);
        const event = handleApiResponse<Event>(eventRes, 201);

        const staffRes = await apiClient.createStaffProfile(contract.id, createStaffProfilePayload(), coordinatorHeaders);
        const staff = handleApiResponse<StaffProfile>(staffRes, 201);
        const otShiftStart = createUnixTimestamp(24);
        const otShiftEnd = addHours(otShiftStart, 41);
        const otShiftRes = await apiClient.createShift(
          contract.id,
          event.id,
          createShiftPayload({ start_time: otShiftStart, end_time: otShiftEnd }),
          coordinatorHeaders
        );
        const otShift = handleApiResponse<Shift>(otShiftRes, 201);
        const otAssignRes = await apiClient.createAssignment(
          contract.id,
          createAssignmentPayload(otShift.id, staff.id),
          accountManagerHeaders
        );
        const otAssign = handleApiResponse<Assignment>(otAssignRes, 201);
        await apiClient.acceptAssignment(contract.id, otAssign.id, staffMemberHeaders);
        await apiClient.confirmAssignment(contract.id, otAssign.id, coordinatorHeaders);

        const contractAt5Res = await apiClient.getContract(contract.id, coordinatorHeaders);
        expect(handleApiResponse<StaffingContract>(contractAt5Res, 200).compliance_risk_score).toBe(5);

        await apiClient.cancelAssignment(contract.id, otAssign.id, coordinatorHeaders);

        const finalContractRes = await apiClient.getContract(contract.id, coordinatorHeaders);
        const finalContract = handleApiResponse<StaffingContract>(finalContractRes, 200);
        expect(finalContract.compliance_risk_score).toBe(0);
      });
    });
  });

  describe('Event Readiness and Compliance Score Interaction', () => {
    describe('P4-EVENT-RISK-01: Automatic downgrade of ready event due to increased risk', () => {
      it('should revert an event from READY_FOR_EXECUTION to PLANNING if risk score rises to 15', async () => {
        const contract = await createAndActivateContract();
        const eventRes = await apiClient.createEvent(contract.id, createEventPayload(), coordinatorHeaders);
        const event = handleApiResponse<Event>(eventRes, 201);

        const shiftRes = await apiClient.createShift(contract.id, event.id, createShiftPayload(), coordinatorHeaders);
        const shift = handleApiResponse<Shift>(shiftRes, 201);

        const staffRes = await apiClient.createStaffProfile(contract.id, createStaffProfilePayload(), coordinatorHeaders);
        const staff = handleApiResponse<StaffProfile>(staffRes, 201);

        const assignRes = await apiClient.createAssignment(contract.id, createAssignmentPayload(shift.id, staff.id), accountManagerHeaders);
        const assignment = handleApiResponse<Assignment>(assignRes, 201);
        await apiClient.acceptAssignment(contract.id, assignment.id, staffMemberHeaders);
        await apiClient.confirmAssignment(contract.id, assignment.id, coordinatorHeaders);

        const contractAtZeroRisk = await apiClient.getContract(contract.id, coordinatorHeaders).then(r => handleApiResponse<StaffingContract>(r, 200));
        expect(contractAtZeroRisk.compliance_risk_score).toBe(0);

        await apiClient.updateEventStatus(contract.id, event.id, { status: EventStatus.READY_FOR_EXECUTION }, coordinatorHeaders);
        const readyEvent = await apiClient.getEvent(contract.id, event.id, coordinatorHeaders).then(r => handleApiResponse<Event>(r, 200));
        expect(readyEvent.status).toBe(EventStatus.READY_FOR_EXECUTION);

        const event2Res = await apiClient.createEvent(contract.id, createEventPayload({ name: 'Second Event' }), coordinatorHeaders);
        const event2 = handleApiResponse<Event>(event2Res, 201);

        for (let i = 0; i < 3; i++) {
          const otStaff = await apiClient.createStaffProfile(contract.id, createStaffProfilePayload({ first_name: `OT_Staff_${i}` }), coordinatorHeaders).then(r => handleApiResponse<StaffProfile>(r, 201));
          const otShift = await apiClient.createShift(contract.id, event2.id, createShiftPayload({ start_time: createUnixTimestamp(i * 100 + 500), end_time: addHours(createUnixTimestamp(i * 100 + 500), 41) }), coordinatorHeaders).then(r => handleApiResponse<Shift>(r, 201));
          const otAssign = await apiClient.createAssignment(contract.id, createAssignmentPayload(otShift.id, otStaff.id), accountManagerHeaders).then(r => handleApiResponse<Assignment>(r, 201));
          await apiClient.acceptAssignment(contract.id, otAssign.id, staffMemberHeaders);
          await apiClient.confirmAssignment(contract.id, otAssign.id, coordinatorHeaders);
        }

        const contractAt15Risk = await apiClient.getContract(contract.id, coordinatorHeaders).then(r => handleApiResponse<StaffingContract>(r, 200));
        expect(contractAt15Risk.compliance_risk_score).toBe(15);

        const finalEvent = await apiClient.getEvent(contract.id, event.id, coordinatorHeaders).then(r => handleApiResponse<Event>(r, 200));
        expect(finalEvent.status).toBe(EventStatus.PLANNING);
      });
    });

    describe('P4-EVENT-RISK-02: Blocking event readiness due to high risk', () => {
      it('should fail to mark an event as READY_FOR_EXECUTION if risk score is 15 or higher', async () => {
        const contract = await createAndActivateContract();
        const eventRes = await apiClient.createEvent(contract.id, createEventPayload(), coordinatorHeaders);
        const event = handleApiResponse<Event>(eventRes, 201);

        const shiftRes = await apiClient.createShift(contract.id, event.id, createShiftPayload(), coordinatorHeaders);
        const shift = handleApiResponse<Shift>(shiftRes, 201);

        const staffRes = await apiClient.createStaffProfile(contract.id, createStaffProfilePayload(), coordinatorHeaders);
        const staff = handleApiResponse<StaffProfile>(staffRes, 201);

        const assignRes = await apiClient.createAssignment(contract.id, createAssignmentPayload(shift.id, staff.id), accountManagerHeaders);
        const assignment = handleApiResponse<Assignment>(assignRes, 201);
        await apiClient.acceptAssignment(contract.id, assignment.id, staffMemberHeaders);
        await apiClient.confirmAssignment(contract.id, assignment.id, coordinatorHeaders);

        const event2Res = await apiClient.createEvent(contract.id, createEventPayload({ name: 'Second Event' }), coordinatorHeaders);
        const event2 = handleApiResponse<Event>(event2Res, 201);

        for (let i = 0; i < 3; i++) {
          const otStaff = await apiClient.createStaffProfile(contract.id, createStaffProfilePayload({ first_name: `OT_Staff_${i}` }), coordinatorHeaders).then(r => handleApiResponse<StaffProfile>(r, 201));
          const otShift = await apiClient.createShift(contract.id, event2.id, createShiftPayload({ start_time: createUnixTimestamp(i * 100 + 500), end_time: addHours(createUnixTimestamp(i * 100 + 500), 41) }), coordinatorHeaders).then(r => handleApiResponse<Shift>(r, 201));
          const otAssign = await apiClient.createAssignment(contract.id, createAssignmentPayload(otShift.id, otStaff.id), accountManagerHeaders).then(r => handleApiResponse<Assignment>(r, 201));
          await apiClient.acceptAssignment(contract.id, otAssign.id, staffMemberHeaders);
          await apiClient.confirmAssignment(contract.id, otAssign.id, coordinatorHeaders);
        }

        const contractAt15Risk = await apiClient.getContract(contract.id, coordinatorHeaders).then(r => handleApiResponse<StaffingContract>(r, 200));
        expect(contractAt15Risk.compliance_risk_score).toBe(15);

        const res = await apiClient.updateEventStatus(contract.id, event.id, { status: EventStatus.READY_FOR_EXECUTION }, coordinatorHeaders);

        validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_ILLEGAL_EVENT_STATE_TRANSITION });
      });
    });
  });

  describe('P4-RISK-03: Re-evaluation of Assignment State on Status Change', () => {
    it('should have its overtime status re-evaluated upon being accepted', async () => {
      const contract = await createAndActivateContract(10000.00);
      const event = await apiClient.createEvent(contract.id, createEventPayload(), coordinatorHeaders)
        .then(r => handleApiResponse<Event>(r, 201));
      const staff = await apiClient.createStaffProfile(contract.id, createStaffProfilePayload({ base_pay_rate_per_hour: 20.00 }), coordinatorHeaders)
        .then(r => handleApiResponse<StaffProfile>(r, 201));

      const shiftA = await apiClient.createShift(contract.id, event.id, createShiftPayload({
        start_time: createUnixTimestamp(100),
        end_time: addHours(createUnixTimestamp(100), 39)
      }), coordinatorHeaders)
        .then(r => handleApiResponse<Shift>(r, 201));
      const assignmentA = await apiClient.createAssignment(contract.id, createAssignmentPayload(shiftA.id, staff.id), accountManagerHeaders)
        .then(r => handleApiResponse<Assignment>(r, 201));

      const shiftB = await apiClient.createShift(contract.id, event.id, createShiftPayload({
        start_time: createUnixTimestamp(200),
        end_time: addHours(createUnixTimestamp(200), 2)
      }), coordinatorHeaders)
        .then(r => handleApiResponse<Shift>(r, 201));
      const assignmentB = await apiClient.createAssignment(contract.id, createAssignmentPayload(shiftB.id, staff.id), accountManagerHeaders)
        .then(r => handleApiResponse<Assignment>(r, 201));

      expect(assignmentB.is_overtime_eligible).toBe(true);
      const contractBefore = await apiClient.getContract(contract.id, coordinatorHeaders).then(r => handleApiResponse<StaffingContract>(r, 200));
      expect(contractBefore.compliance_risk_score).toBe(5);

      await apiClient.cancelAssignment(contract.id, assignmentA.id, coordinatorHeaders);

      const acceptRes = await apiClient.acceptAssignment(contract.id, assignmentB.id, staffMemberHeaders);
      handleApiResponse<Assignment>(acceptRes, 200);

      const confirmRes = await apiClient.confirmAssignment(contract.id, assignmentB.id, coordinatorHeaders);
      handleApiResponse<Assignment>(confirmRes, 200);

      const finalAssignmentB = await apiClient.getAssignment(contract.id, assignmentB.id, coordinatorHeaders)
        .then(r => handleApiResponse<Assignment>(r, 200));
      const finalContract = await apiClient.getContract(contract.id, coordinatorHeaders)
        .then(r => handleApiResponse<StaffingContract>(r, 200));

      expect(finalAssignmentB.is_overtime_eligible).toBe(false);
      expect(finalContract.compliance_risk_score).toBe(0);
    });
  });

  describe('P3-ACCEPT-01.1: Risk decreases when hours drop below OT after ACCEPT', () => {
    it('should re-evaluate risk when accepting assignment after other hours are removed', async () => {
      const contract = await createAndActivateContract(5000.00);
      const event = await apiClient.createEvent(contract.id, createEventPayload(), coordinatorHeaders)
        .then(r => handleApiResponse<Event>(r, 201));
      const staff = await apiClient.createStaffProfile(contract.id, createStaffProfilePayload({ base_pay_rate_per_hour: 20.00 }), coordinatorHeaders)
        .then(r => handleApiResponse<StaffProfile>(r, 201));

      const shift38h = await apiClient.createShift(contract.id, event.id, createShiftPayload({
        start_time: createUnixTimestamp(24),
        end_time: addHours(createUnixTimestamp(24), 38)
      }), coordinatorHeaders)
        .then(r => handleApiResponse<Shift>(r, 201));

      const assign38h = await apiClient.createAssignment(contract.id, createAssignmentPayload(shift38h.id, staff.id), accountManagerHeaders)
        .then(r => handleApiResponse<Assignment>(r, 201));
      await apiClient.acceptAssignment(contract.id, assign38h.id, staffMemberHeaders);
      await apiClient.confirmAssignment(contract.id, assign38h.id, coordinatorHeaders);

      const shift4h = await apiClient.createShift(contract.id, event.id, createShiftPayload({
        start_time: createUnixTimestamp(100),
        end_time: addHours(createUnixTimestamp(100), 4)
      }), coordinatorHeaders)
        .then(r => handleApiResponse<Shift>(r, 201));

      const assign4h = await apiClient.createAssignment(contract.id, createAssignmentPayload(shift4h.id, staff.id), accountManagerHeaders)
        .then(r => handleApiResponse<Assignment>(r, 201));

      expect(assign4h.is_overtime_eligible).toBe(true);
      const contractBefore = await apiClient.getContract(contract.id, coordinatorHeaders)
        .then(r => handleApiResponse<StaffingContract>(r, 200));
      expect(contractBefore.compliance_risk_score).toBe(5);

      await apiClient.cancelAssignment(contract.id, assign38h.id, coordinatorHeaders);

      const contractAfterCancel = await apiClient.getContract(contract.id, coordinatorHeaders)
        .then(r => handleApiResponse<StaffingContract>(r, 200));
      expect(contractAfterCancel.compliance_risk_score).toBe(0);

      const acceptRes = await apiClient.acceptAssignment(contract.id, assign4h.id, staffMemberHeaders);
      const acceptedAssignment = handleApiResponse<Assignment>(acceptRes, 200);

      const confirmRes = await apiClient.confirmAssignment(contract.id, assign4h.id, coordinatorHeaders);
      const confirmedAssignment = handleApiResponse<Assignment>(confirmRes, 200);

      expect(confirmedAssignment.is_overtime_eligible).toBe(false);
      expect(confirmedAssignment.provisional_cost).toBe(80.00);

      const contractAfterConfirm = await apiClient.getContract(contract.id, coordinatorHeaders)
        .then(r => handleApiResponse<StaffingContract>(r, 200));
      expect(contractAfterConfirm.compliance_risk_score).toBe(0);
    });
  });

  describe('P1-READ-01.1: Read-only endpoints must work for non-ACTIVE contracts', () => {
    it('should allow reading events from a CLOSED contract', async () => {
      const contract = await createAndActivateContract(1000.00);
      const event = await apiClient.createEvent(contract.id, createEventPayload(), coordinatorHeaders)
        .then(r => handleApiResponse<Event>(r, 201));
      const staff = await apiClient.createStaffProfile(contract.id, createStaffProfilePayload(), coordinatorHeaders)
        .then(r => handleApiResponse<StaffProfile>(r, 201));
      const shift = await apiClient.createShift(contract.id, event.id, createShiftPayload(), coordinatorHeaders)
        .then(r => handleApiResponse<Shift>(r, 201));

      const assignment = await apiClient.createAssignment(contract.id, createAssignmentPayload(shift.id, staff.id), accountManagerHeaders)
        .then(r => handleApiResponse<Assignment>(r, 201));
      await apiClient.acceptAssignment(contract.id, assignment.id, staffMemberHeaders);
      await apiClient.confirmAssignment(contract.id, assignment.id, coordinatorHeaders);
      await apiClient.initiatePayroll(contract.id, coordinatorHeaders);
      await apiClient.finalizePayroll(contract.id, coordinatorHeaders);

      const closedContract = await apiClient.getContract(contract.id, coordinatorHeaders)
        .then(r => handleApiResponse<StaffingContract>(r, 200));
      expect(closedContract.status).toBe('CLOSED');

      const eventsRes = await apiClient.getEvents(contract.id, coordinatorHeaders);

      expect(eventsRes.status).toBe(200);
      const events = handleApiResponse<Event[]>(eventsRes, 200, { expectPaginated: true });
      expect(events.length).toBeGreaterThan(0);
    });

    it('should allow reading assignments from a PLANNING contract', async () => {
      const contractRes = await apiClient.createContract(createContractPayload(), coordinatorHeaders);
      const contract = handleApiResponse<StaffingContract>(contractRes, 201);

      expect(contract.status).toBe('PLANNING');

      const assignmentsRes = await apiClient.getAssignments(contract.id, coordinatorHeaders);

      expect(assignmentsRes.status).toBe(200);
      const assignments = handleApiResponse<Assignment[]>(assignmentsRes, 200, { expectPaginated: true });
      expect(assignments).toEqual([]);
    });
  });

  describe('Certification Edge Cases', () => {
    describe('P4-CERT-01: Staff with Multiple Certifications', () => {
      it('should allow staff with multiple certifications to work shifts requiring either certification', async () => {
        const contract = await createAndActivateContract(2000.00);
        const eventRes = await apiClient.createEvent(
          contract.id,
          createEventPayload({ name: 'Multi-Cert Event' }),
          coordinatorHeaders
        );
        const event = handleApiResponse<Event>(eventRes, 201);

        const staffRes = await apiClient.createStaffProfile(
          contract.id,
          createStaffProfilePayload({
            first_name: 'Multi',
            last_name: 'Certified',
            base_pay_rate_per_hour: 25.00
          }),
          coordinatorHeaders
        );
        const staff = handleApiResponse<StaffProfile>(staffRes, 201);

        const foodCertRes = await apiClient.addCertification(
          contract.id,
          staff.id,
          {
            name: CertificationType.FOOD_HANDLER_PERMIT,
            issued_date: '2024-01-01',
            expiry_date: '2030-01-01'
          },
          coordinatorHeaders
        );
        handleApiResponse<StaffProfile>(foodCertRes, 201);

        const alcoholCertRes = await apiClient.addCertification(
          contract.id,
          staff.id,
          {
            name: CertificationType.ALCOHOL_SERVICE_LICENSE,
            issued_date: '2024-02-01',
            expiry_date: '2030-02-01'
          },
          coordinatorHeaders
        );
        const updatedStaff = handleApiResponse<StaffProfile>(alcoholCertRes, 201);

        expect(updatedStaff.certifications).toHaveLength(2);
        expect(updatedStaff.certifications.map(c => c.name)).toContain(CertificationType.FOOD_HANDLER_PERMIT);
        expect(updatedStaff.certifications.map(c => c.name)).toContain(CertificationType.ALCOHOL_SERVICE_LICENSE);

        const baseTime = createUnixTimestamp(24);

        const foodShiftRes = await apiClient.createShift(
          contract.id,
          event.id,
          createShiftPayload({
            role_name: 'Food Server',
            certification_needed: CertificationType.FOOD_HANDLER_PERMIT,
            start_time: baseTime,
            end_time: addHours(baseTime, 8)
          }),
          coordinatorHeaders
        );
        const foodShift = handleApiResponse<Shift>(foodShiftRes, 201);

        const foodAssignmentRes = await apiClient.createAssignment(
          contract.id,
          createAssignmentPayload(foodShift.id, staff.id),
          accountManagerHeaders
        );
        const foodAssignment = handleApiResponse<Assignment>(foodAssignmentRes, 201);
        expect(foodAssignment.status).toBe('PROPOSED');

        const alcoholShiftRes = await apiClient.createShift(
          contract.id,
          event.id,
          createShiftPayload({
            role_name: 'Bartender',
            certification_needed: CertificationType.ALCOHOL_SERVICE_LICENSE,
            start_time: addHours(baseTime, 20),
            end_time: addHours(baseTime, 28)
          }),
          coordinatorHeaders
        );
        const alcoholShift = handleApiResponse<Shift>(alcoholShiftRes, 201);

        const alcoholAssignmentRes = await apiClient.createAssignment(
          contract.id,
          createAssignmentPayload(alcoholShift.id, staff.id),
          accountManagerHeaders
        );
        const alcoholAssignment = handleApiResponse<Assignment>(alcoholAssignmentRes, 201);
        expect(alcoholAssignment.status).toBe('PROPOSED');

        const generalShiftRes = await apiClient.createShift(
          contract.id,
          event.id,
          createShiftPayload({
            role_name: 'General Helper',
            certification_needed: CertificationType.NONE,
            start_time: addHours(baseTime, 40),
            end_time: addHours(baseTime, 48)
          }),
          coordinatorHeaders
        );
        const generalShift = handleApiResponse<Shift>(generalShiftRes, 201);

        const generalAssignmentRes = await apiClient.createAssignment(
          contract.id,
          createAssignmentPayload(generalShift.id, staff.id),
          accountManagerHeaders
        );
        const generalAssignment = handleApiResponse<Assignment>(generalAssignmentRes, 201);
        expect(generalAssignment.status).toBe('PROPOSED');
      });
    });

    describe('P4-CERT-02: Expired Certification Validation', () => {
      it('should reject assignment when staff certification is expired', async () => {
        const contract = await createAndActivateContract(2000.00);
        const eventRes = await apiClient.createEvent(
          contract.id,
          createEventPayload({ name: 'Expired Cert Event' }),
          coordinatorHeaders
        );
        const event = handleApiResponse<Event>(eventRes, 201);

        const staffRes = await apiClient.createStaffProfile(
          contract.id,
          createStaffProfilePayload({
            first_name: 'Expired',
            last_name: 'Certificate',
            base_pay_rate_per_hour: 20.00
          }),
          coordinatorHeaders
        );
        const staff = handleApiResponse<StaffProfile>(staffRes, 201);

        const yesterday = new Date();
        yesterday.setDate(yesterday.getDate() - 1);
        const yesterdayStr = yesterday.toISOString().split('T')[0];

        const certRes = await apiClient.addCertification(
          contract.id,
          staff.id,
          {
            name: CertificationType.FOOD_HANDLER_PERMIT,
            issued_date: '2022-01-01',
            expiry_date: yesterdayStr
          },
          coordinatorHeaders
        );
        const staffWithCert = handleApiResponse<StaffProfile>(certRes, 201);

        expect(staffWithCert.certifications).toHaveLength(1);
        expect(staffWithCert.certifications[0].expiry_date).toBe(yesterdayStr);

        const baseTime = createUnixTimestamp(24);

        const shiftRes = await apiClient.createShift(
          contract.id,
          event.id,
          createShiftPayload({
            role_name: 'Food Server',
            certification_needed: CertificationType.FOOD_HANDLER_PERMIT,
            start_time: baseTime,
            end_time: addHours(baseTime, 8)
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
          expectedErrorId: ApiErrorId.ERR_CERTIFICATION_MISSING
        });
      });

      it('should accept assignment when certification expires in the future', async () => {
        const contract = await createAndActivateContract(2000.00);
        const eventRes = await apiClient.createEvent(
          contract.id,
          createEventPayload({ name: 'Valid Cert Event' }),
          coordinatorHeaders
        );
        const event = handleApiResponse<Event>(eventRes, 201);

        const staffRes = await apiClient.createStaffProfile(
          contract.id,
          createStaffProfilePayload({
            first_name: 'Valid',
            last_name: 'Certificate',
            base_pay_rate_per_hour: 20.00
          }),
          coordinatorHeaders
        );
        const staff = handleApiResponse<StaffProfile>(staffRes, 201);

        const tomorrow = new Date();
        tomorrow.setDate(tomorrow.getDate() + 1);
        const tomorrowStr = tomorrow.toISOString().split('T')[0];

        const certRes = await apiClient.addCertification(
          contract.id,
          staff.id,
          {
            name: CertificationType.ALCOHOL_SERVICE_LICENSE,
            issued_date: '2024-01-01',
            expiry_date: tomorrowStr
          },
          coordinatorHeaders
        );
        handleApiResponse<StaffProfile>(certRes, 201);

        const baseTime = createUnixTimestamp(24);

        const shiftRes = await apiClient.createShift(
          contract.id,
          event.id,
          createShiftPayload({
            role_name: 'Bartender',
            certification_needed: CertificationType.ALCOHOL_SERVICE_LICENSE,
            start_time: baseTime,
            end_time: addHours(baseTime, 8)
          }),
          coordinatorHeaders
        );
        const shift = handleApiResponse<Shift>(shiftRes, 201);

        const assignmentRes = await apiClient.createAssignment(
          contract.id,
          createAssignmentPayload(shift.id, staff.id),
          accountManagerHeaders
        );

        const assignment = handleApiResponse<Assignment>(assignmentRes, 201);
        expect(assignment.status).toBe('PROPOSED');
      });
    });
  });
  describe('TC-REST-01: Contract-Scoped Rest Periods', () => {
    it('should allow assignments under different contracts without 8-hour gap', async () => {
      const contractA = await createAndActivateContract(1000.00);
      const eventARes = await apiClient.createEvent(
        contractA.id,
        createEventPayload({ name: 'Contract A Event' }),
        coordinatorHeaders
      );
      const eventA = handleApiResponse<Event>(eventARes, 201);
      const staffARes = await apiClient.createStaffProfile(
        contractA.id,
        createStaffProfilePayload({ first_name: 'Rest', last_name: 'Tester A' }),
        coordinatorHeaders
      );
      const staffA = handleApiResponse<StaffProfile>(staffARes, 201);

      const baseTime = createUnixTimestamp(24);

      const shiftARes = await apiClient.createShift(
        contractA.id,
        eventA.id,
        createShiftPayload({
          role_name: 'Early Shift',
          start_time: baseTime,
          end_time: addHours(baseTime, 4)
        }),
        coordinatorHeaders
      );
      const shiftA = handleApiResponse<Shift>(shiftARes, 201);

      const contractB = await createAndActivateContract(1000.00);
      const eventBRes = await apiClient.createEvent(
        contractB.id,
        createEventPayload({ name: 'Contract B Event' }),
        coordinatorHeaders
      );
      const eventB = handleApiResponse<Event>(eventBRes, 201);
      const staffBRes = await apiClient.createStaffProfile(
        contractB.id,
        createStaffProfilePayload({ first_name: 'Rest', last_name: 'Tester B' }),
        coordinatorHeaders
      );
      const staffB = handleApiResponse<StaffProfile>(staffBRes, 201);

      const shiftBRes = await apiClient.createShift(
        contractB.id,
        eventB.id,
        createShiftPayload({
          role_name: 'Late Shift',
          start_time: addHours(baseTime, 6),
          end_time: addHours(baseTime, 10)
        }),
        coordinatorHeaders
      );
      const shiftB = handleApiResponse<Shift>(shiftBRes, 201);

      const assignmentARes = await apiClient.createAssignment(
        contractA.id,
        createAssignmentPayload(shiftA.id, staffA.id),
        accountManagerHeaders
      );
      const assignmentA = handleApiResponse<Assignment>(assignmentARes, 201);

      const assignmentBRes = await apiClient.createAssignment(
        contractB.id,
        createAssignmentPayload(shiftB.id, staffB.id),
        accountManagerHeaders
      );
      const assignmentB = handleApiResponse<Assignment>(assignmentBRes, 201);

      expect(assignmentA.status).toBe(AssignmentStatus.PROPOSED);
      expect(assignmentB.status).toBe(AssignmentStatus.PROPOSED);
    });
  });
});
