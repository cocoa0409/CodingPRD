import {
  apiClient,
  buildUserHeaders,
  handleApiResponse,
  validateApiResponseStructure,
  validateErrorEnvelope,
  assertStaffingContract,
  assertEvent,
  assertShift,
  assertStaffProfile, assertConflictPairing,
  createContractPayload,
  createEventPayload,
  createShiftPayload,
  createStaffProfilePayload,
  createAssignmentPayload,
  createConflictPairingPayload,
  createCertificationPayload,
  StaffingContract,
  Event,
  Shift,
  StaffProfile,
  Assignment,
  ConflictPairing,
  ContractStatus,
  EventStatus,
  UserRole,
  CertificationType,
  ApiErrorId
} from '../../../test-helpers';

describe('Phase 1: Endpoint Validation', () => {
  const coordinatorHeaders = buildUserHeaders('coordinator-1', UserRole.StaffingCoordinator);
  const staffMemberHeaders = buildUserHeaders('staff-1', UserRole.StaffMember);
  const accountManagerHeaders = buildUserHeaders('manager-1', UserRole.AccountManager);

  const NON_EXISTENT_UUID = '00000000-0000-0000-0000-000000000000';

  async function fetchAllContracts(headers: Record<string, string>): Promise<StaffingContract[]> {
    let offset = 0;
    const all: StaffingContract[] = [];
    while (true) {
      const res = await apiClient.getContracts(headers, { limit: 100, offset });
      const envelope = validateApiResponseStructure<StaffingContract[]>(res, { expectPaginated: true });
      all.push(...envelope.data);
      if (!envelope.meta.has_more) break;
      offset += envelope.meta.limit ?? 0;
    }
    return all;
  }

  describe('StaffingContract Resource', () => {
    describe('P1-CONTRACT-01.1: Create a new Staffing Contract', () => {
      it('should successfully create a contract with valid data', async () => {
        const payload = createContractPayload({
          client_name: 'Gala for the Arts 2024',
          total_budget: 50000.00,
        });

        const res = await apiClient.createContract(payload, coordinatorHeaders);
        const contract = handleApiResponse<StaffingContract>(res, 201);

        assertStaffingContract(contract);

        expect(contract.client_name).toBe('Gala for the Arts 2024');
        expect(contract.total_budget).toBe(50000.00);
        expect(contract.status).toBe(ContractStatus.PLANNING);
        expect(contract.budget_balance).toBe(50000.00);
        expect(contract.compliance_risk_score).toBe(0);
      });
    });

    describe('P1-CONTRACT-02.1: List all Staffing Contracts', () => {
      it('should retrieve list containing created contracts', async () => {
        const contract1Payload = createContractPayload({ client_name: 'Contract 1' });
        const contract2Payload = createContractPayload({ client_name: 'Contract 2' });

        const res1 = await apiClient.createContract(contract1Payload, coordinatorHeaders);
        const contract1 = handleApiResponse<StaffingContract>(res1, 201);

        const res2 = await apiClient.createContract(contract2Payload, coordinatorHeaders);
        const contract2 = handleApiResponse<StaffingContract>(res2, 201);

        const contracts = await fetchAllContracts(coordinatorHeaders);

        expect(contracts.length).toBeGreaterThanOrEqual(2);
        const contractIds = contracts.map(c => c.id);
        expect(contractIds).toContain(contract1.id);
        expect(contractIds).toContain(contract2.id);
      });
    });

    describe('P1-CONTRACT-02.2: Pagination for Staffing Contracts', () => {
      beforeEach(async () => {
        await apiClient.createContract(createContractPayload({ client_name: 'PagiContract 1' }), coordinatorHeaders);
        await apiClient.createContract(createContractPayload({ client_name: 'PagiContract 2' }), coordinatorHeaders);
        await apiClient.createContract(createContractPayload({ client_name: 'PagiContract 3' }), coordinatorHeaders);
      });

      it('should respect the limit parameter', async () => {
        const listRes = await apiClient.getContracts(coordinatorHeaders, { limit: 2 });
        const contracts = handleApiResponse<StaffingContract[]>(listRes, 200, { expectPaginated: true });
        expect(contracts.length).toBe(2);
      });

      it('should respect the offset parameter', async () => {
        const fullListRes = await apiClient.getContracts(coordinatorHeaders, { limit: 100 });
        const fullList = handleApiResponse<StaffingContract[]>(fullListRes, 200, { expectPaginated: true });
        const secondContractId = fullList[1].id;

        const listRes = await apiClient.getContracts(coordinatorHeaders, { limit: 1, offset: 1 });
        const contracts = handleApiResponse<StaffingContract[]>(listRes, 200, { expectPaginated: true });

        expect(contracts.length).toBe(1);
        expect(contracts[0].id).toBe(secondContractId);
      });
    });

    describe('P1-CONTRACT-03.1: Get specific Staffing Contract', () => {
      it('should retrieve an existing contract by ID', async () => {
        const payload = createContractPayload({ client_name: 'Test Contract' });
        const createRes = await apiClient.createContract(payload, coordinatorHeaders);
        const createdContract = handleApiResponse<StaffingContract>(createRes, 201);

        const getRes = await apiClient.getContract(createdContract.id, coordinatorHeaders);
        const retrievedContract = handleApiResponse<StaffingContract>(getRes, 200);

        assertStaffingContract(retrievedContract);
        expect(retrievedContract.id).toBe(createdContract.id);
        expect(retrievedContract.client_name).toBe('Test Contract');
      });
    });

    describe('P1-CONTRACT-03.2: Get non-existent Staffing Contract', () => {
      it('should return 404 for non-existent contract ID', async () => {
        const res = await apiClient.getContract(NON_EXISTENT_UUID, coordinatorHeaders);
        validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_CONTRACT_NOT_FOUND });
      });
    });

    describe('P1-CONTRACT-04.1: Activate non-existent Staffing Contract', () => {
      it('should return 404 when activating non-existent contract', async () => {
        const res = await apiClient.activateContract(NON_EXISTENT_UUID, coordinatorHeaders);
        validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_CONTRACT_NOT_FOUND });
      });
    });
  });

  describe('Event Resource', () => {
    let testContract: StaffingContract;

    beforeEach(async () => {
      const contractRes = await apiClient.createContract(
        createContractPayload({ client_name: 'Event Test Contract' }),
        coordinatorHeaders
      );
      testContract = handleApiResponse<StaffingContract>(contractRes, 201);

      const activateRes = await apiClient.activateContract(testContract.id, coordinatorHeaders);
      testContract = handleApiResponse<StaffingContract>(activateRes, 200);
    });

    describe('P1-EVENT-01.1: Create Event under existing Contract', () => {
      it('should successfully create an event', async () => {
        const payload = createEventPayload({
          name: 'Main Reception',
          start_time: 1672531200,
          end_time: 1672552800,
        });

        const res = await apiClient.createEvent(testContract.id, payload, coordinatorHeaders);
        const event = handleApiResponse<Event>(res, 201);

        assertEvent(event);
        expect(event.name).toBe('Main Reception');
        expect(event.contract_id).toBe(testContract.id);
        expect(event.status).toBe(EventStatus.PLANNING);
      });
    });

    describe('P1-EVENT-01.2: Create Event under non-existent Contract', () => {
      it('should return 404 for non-existent contract', async () => {
        const payload = createEventPayload();
        const res = await apiClient.createEvent(NON_EXISTENT_UUID, payload, coordinatorHeaders);
        validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_CONTRACT_NOT_FOUND });
      });
    });

    describe('P1-EVENT-02.1: List Events for non-existent Contract', () => {
      it('should return 404 when listing events for non-existent contract', async () => {
        const res = await apiClient.getEvents(NON_EXISTENT_UUID, coordinatorHeaders);
        validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_CONTRACT_NOT_FOUND });
      });
    });

    describe('P1-EVENT-02.2: Pagination for Events', () => {
      beforeEach(async () => {
        await apiClient.createEvent(testContract.id, createEventPayload({ name: 'Event A' }), coordinatorHeaders);
        await apiClient.createEvent(testContract.id, createEventPayload({ name: 'Event B' }), coordinatorHeaders);
        await apiClient.createEvent(testContract.id, createEventPayload({ name: 'Event C' }), coordinatorHeaders);
      });

      it('should respect the limit parameter for events', async () => {
        const listRes = await apiClient.getEvents(testContract.id, coordinatorHeaders, { limit: 1 });
        const events = handleApiResponse<Event[]>(listRes, 200, { expectPaginated: true });
        expect(events.length).toBe(1);
      });

      it('should accept requests with limit=100', async () => {
        const res = await apiClient.getContracts(coordinatorHeaders, { limit: 100 });

        expect(res.status).toBe(200);
        const contracts = handleApiResponse<StaffingContract[]>(res, 200, { expectPaginated: true });
        expect(contracts.length).toBeLessThanOrEqual(100);
      });

      it('should respect the offset parameter for events', async () => {
        const fullListRes = await apiClient.getEvents(testContract.id, coordinatorHeaders);
        const fullList = handleApiResponse<Event[]>(fullListRes, 200, { expectPaginated: true });
        const secondEventId = fullList[1].id;

        const listRes = await apiClient.getEvents(testContract.id, coordinatorHeaders, { limit: 1, offset: 1 });
        const events = handleApiResponse<Event[]>(listRes, 200, { expectPaginated: true });

        expect(events.length).toBe(1);
        expect(events[0].id).toBe(secondEventId);
      });
    });

    describe('P1-EVENT-03.1: Get specific existing Event', () => {
      it('should retrieve an existing event', async () => {
        const eventPayload = createEventPayload({ name: 'Test Event' });
        const createRes = await apiClient.createEvent(testContract.id, eventPayload, coordinatorHeaders);
        const createdEvent = handleApiResponse<Event>(createRes, 201);

        const getRes = await apiClient.getEvent(testContract.id, createdEvent.id, coordinatorHeaders);
        const retrievedEvent = handleApiResponse<Event>(getRes, 200);

        assertEvent(retrievedEvent);
        expect(retrievedEvent.id).toBe(createdEvent.id);
        expect(retrievedEvent.name).toBe('Test Event');
      });
    });

    describe('P1-EVENT-03.2: Get non-existent Event', () => {
      it('should return 404 for non-existent event ID', async () => {
        const res = await apiClient.getEvent(testContract.id, NON_EXISTENT_UUID, coordinatorHeaders);
        validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_EVENT_NOT_FOUND });
      });
    });

    describe('P1-EVENT-03.3: Get Event with non-existent contract', () => {
      it('should return 404 when contract does not exist', async () => {
        const eventRes = await apiClient.createEvent(
          testContract.id,
          createEventPayload(),
          coordinatorHeaders
        );
        const event = handleApiResponse<Event>(eventRes, 201);

        const res = await apiClient.getEvent(NON_EXISTENT_UUID, event.id, coordinatorHeaders);
        validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_EVENT_NOT_FOUND });
      });
    });

    describe('P1-EVENT-03.4: Data isolation - Event from different contract', () => {
      it('should return 404 when accessing event from different contract', async () => {
        const contractARes = await apiClient.createContract(
          createContractPayload({ client_name: 'Contract A' }),
          coordinatorHeaders
        );
        let contractA = handleApiResponse<StaffingContract>(contractARes, 201);
        const contractBRes = await apiClient.createContract(
          createContractPayload({ client_name: 'Contract B' }),
          coordinatorHeaders
        );
        let contractB = handleApiResponse<StaffingContract>(contractBRes, 201);

        contractA = handleApiResponse<StaffingContract>(await apiClient.activateContract(contractA.id, coordinatorHeaders), 200);
        contractB = handleApiResponse<StaffingContract>(await apiClient.activateContract(contractB.id, coordinatorHeaders), 200);

        const eventRes = await apiClient.createEvent(
          contractB.id,
          createEventPayload({ name: 'Contract B Event' }),
          coordinatorHeaders
        );
        const eventB = handleApiResponse<Event>(eventRes, 201);

        const res = await apiClient.getEvent(contractA.id, eventB.id, coordinatorHeaders);
        validateErrorEnvelope(res, {
          expectedErrorId: ApiErrorId.ERR_EVENT_NOT_FOUND
        });
      });
    });

    describe('P1-EVENT-04.1: Update non-existent Event', () => {
      it('should return 404 when updating non-existent event', async () => {
        const res = await apiClient.updateEventStatus(
          testContract.id,
          NON_EXISTENT_UUID,
          { status: EventStatus.READY_FOR_EXECUTION },
          coordinatorHeaders
        );
        validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_EVENT_NOT_FOUND });
      });
    });

    describe('P1-EVENT-04.2: Data isolation - Update Event from different contract', () => {
      it('should return 404 when updating event from different contract', async () => {
        const contractARes = await apiClient.createContract(
          createContractPayload({ client_name: 'Contract A' }),
          coordinatorHeaders
        );
        let contractA = handleApiResponse<StaffingContract>(contractARes, 201);

        const contractBRes = await apiClient.createContract(
          createContractPayload({ client_name: 'Contract B' }),
          coordinatorHeaders
        );
        let contractB = handleApiResponse<StaffingContract>(contractBRes, 201);

        contractA = handleApiResponse<StaffingContract>(await apiClient.activateContract(contractA.id, coordinatorHeaders), 200);
        contractB = handleApiResponse<StaffingContract>(await apiClient.activateContract(contractB.id, coordinatorHeaders), 200);

        const eventRes = await apiClient.createEvent(
          contractB.id,
          createEventPayload(),
          coordinatorHeaders
        );
        const eventB = handleApiResponse<Event>(eventRes, 201);

        const res = await apiClient.updateEventStatus(
          contractA.id,
          eventB.id,
          { status: EventStatus.READY_FOR_EXECUTION },
          coordinatorHeaders
        );
        validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_EVENT_NOT_FOUND });
      });
    });
  });

  describe('Shift Resource', () => {
    let contract: StaffingContract;
    let event: Event;

    beforeEach(async () => {
      const contractRes = await apiClient.createContract(
        createContractPayload({ client_name: 'Shift Test Contract' }),
        coordinatorHeaders
      );
      contract = handleApiResponse<StaffingContract>(contractRes, 201);

      const activateRes = await apiClient.activateContract(contract.id, coordinatorHeaders);
      contract = handleApiResponse<StaffingContract>(activateRes, 200);

      const eventRes = await apiClient.createEvent(
        contract.id,
        createEventPayload({ name: 'Shift Test Event' }),
        coordinatorHeaders
      );
      event = handleApiResponse<Event>(eventRes, 201);
    });

    describe('P1-SHIFT-01.1: Create Shift with invalid times', () => {
      it('should return 400 when end_time is before start_time', async () => {
        const shiftPayload = createShiftPayload({
          start_time: 1672534800,
          end_time: 1672531200,
        });
        const res = await apiClient.createShift(
          contract.id,
          event.id,
          shiftPayload,
          coordinatorHeaders
        );
        validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_INVALID_SHIFT_TIMES });
      });

      it('should return 400 when start_time is equal to end_time', async () => {
        const now = 1672534800;
        const shiftPayload = createShiftPayload({
          start_time: now,
          end_time: now,
        });
        const res = await apiClient.createShift(
          contract.id,
          event.id,
          shiftPayload,
          coordinatorHeaders
        );
        validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_INVALID_SHIFT_TIMES });
      });
    });

    describe('P1-SHIFT-01.2: Create Shift under non-existent Event', () => {
      it('should return 404 when creating shift under non-existent event', async () => {
        const shiftPayload = createShiftPayload();
        const res = await apiClient.createShift(
          contract.id,
          NON_EXISTENT_UUID,
          shiftPayload,
          coordinatorHeaders
        );
        validateErrorEnvelope(res, {
          expectedErrorId: ApiErrorId.ERR_EVENT_NOT_FOUND
        });
      });
    });

    describe('P1-SHIFT-02.1: Get specific existing Shift', () => {
      it('should retrieve an existing shift', async () => {
        const shiftPayload = createShiftPayload({ role_name: 'Server' });
        const createRes = await apiClient.createShift(
          contract.id,
          event.id,
          shiftPayload,
          coordinatorHeaders
        );
        const createdShift = handleApiResponse<Shift>(createRes, 201);

        const getRes = await apiClient.getShift(
          contract.id,
          event.id,
          createdShift.id,
          coordinatorHeaders
        );
        const retrievedShift = handleApiResponse<Shift>(getRes, 200);

        assertShift(retrievedShift);
        expect(retrievedShift.id).toBe(createdShift.id);
        expect(retrievedShift.role_name).toBe('Server');
      });
    });

    describe('P1-SHIFT-02.2: Get non-existent Shift', () => {
      it('should return 404 for non-existent shift ID', async () => {
        const res = await apiClient.getShift(
          contract.id,
          event.id,
          NON_EXISTENT_UUID,
          coordinatorHeaders
        );
        validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_SHIFT_NOT_FOUND });
      });
    });

    describe('P1-SHIFT-02.3: Data isolation - Get shift from wrong event', () => {
      it('should return 404 when retrieving shift through wrong event', async () => {
        const eventARes = await apiClient.createEvent(
          contract.id,
          createEventPayload({ name: 'Event A' }),
          coordinatorHeaders
        );
        const eventA = handleApiResponse<Event>(eventARes, 201);

        const eventBRes = await apiClient.createEvent(
          contract.id,
          createEventPayload({ name: 'Event B' }),
          coordinatorHeaders
        );
        const eventB = handleApiResponse<Event>(eventBRes, 201);

        const shiftRes = await apiClient.createShift(
          contract.id,
          eventB.id,
          createShiftPayload({ role_name: 'Event B Shift' }),
          coordinatorHeaders
        );
        const shiftB = handleApiResponse<Shift>(shiftRes, 201);

        const res = await apiClient.getShift(
          contract.id,
          eventA.id,
          shiftB.id,
          coordinatorHeaders
        );

        validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_SHIFT_NOT_FOUND });
      });
    });

    describe('P1-SHIFT-02.4: Data isolation - Get shift from different contract', () => {
      it('should return 404 when retrieving shift through wrong contract', async () => {
        const contractARes = await apiClient.createContract(
          createContractPayload({ client_name: 'Contract A' }),
          coordinatorHeaders
        );
        const contractA = handleApiResponse<StaffingContract>(contractARes, 201);
        await apiClient.activateContract(contractA.id, coordinatorHeaders);

        const contractBRes = await apiClient.createContract(
          createContractPayload({ client_name: 'Contract B' }),
          coordinatorHeaders
        );
        let contractB = handleApiResponse<StaffingContract>(contractBRes, 201);

        const activateB = await apiClient.activateContract(contractB.id, coordinatorHeaders);
        contractB = handleApiResponse<StaffingContract>(activateB, 200);

        const eventBRes = await apiClient.createEvent(
          contractB.id,
          createEventPayload({ name: 'Event B' }),
          coordinatorHeaders
        );
        const eventB = handleApiResponse<Event>(eventBRes, 201);
        const shiftBRes = await apiClient.createShift(
          contractB.id,
          eventB.id,
          createShiftPayload({ role_name: 'Event B Shift' }),
          coordinatorHeaders
        );
        const shiftB = handleApiResponse<Shift>(shiftBRes, 201);

        const res = await apiClient.getShift(
          contractA.id,
          eventB.id,
          shiftB.id,
          coordinatorHeaders
        );

        validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_SHIFT_NOT_FOUND });
      });
    });
  });

  describe('StaffProfile Resource', () => {
    describe('P1-STAFF-01.1: Create new Staff Profile', () => {
      it('should successfully create a staff profile', async () => {
        const contractRes = await apiClient.createContract(
          createContractPayload(),
          coordinatorHeaders
        );
        let contract = handleApiResponse<StaffingContract>(contractRes, 201);

        const activateRes = await apiClient.activateContract(contract.id, coordinatorHeaders);
        contract = handleApiResponse<StaffingContract>(activateRes, 200);

        const staffPayload = createStaffProfilePayload({
          first_name: 'Jane',
          last_name: 'Doe',
          base_pay_rate_per_hour: 25.50,
        });

        const res = await apiClient.createStaffProfile(
          contract.id,
          staffPayload,
          coordinatorHeaders
        );
        const staff = handleApiResponse<StaffProfile>(res, 201);

        assertStaffProfile(staff);
        expect(staff.first_name).toBe('Jane');
        expect(staff.last_name).toBe('Doe');
        expect(staff.base_pay_rate_per_hour).toBe(25.50);
        expect(staff.contract_id).toBe(contract.id);
      });
    });

    describe('P1-STAFF-01.2: Create Staff Profile under non-existent contract', () => {
      it('should return 404 for non-existent contract', async () => {
        const staffPayload = createStaffProfilePayload();
        const res = await apiClient.createStaffProfile(
          NON_EXISTENT_UUID,
          staffPayload,
          coordinatorHeaders
        );
        validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_CONTRACT_NOT_FOUND });
      });
    });

    describe('P1-STAFF-02.1: Data isolation - StaffProfile from different contract', () => {
      it('should return 404 when accessing staff from different contract', async () => {
        const contractARes = await apiClient.createContract(
          createContractPayload({ client_name: 'Contract A' }),
          coordinatorHeaders
        );
        const contractA = handleApiResponse<StaffingContract>(contractARes, 201);

        const contractBRes = await apiClient.createContract(
          createContractPayload({ client_name: 'Contract B' }),
          coordinatorHeaders
        );
        let contractB = handleApiResponse<StaffingContract>(contractBRes, 201);

        contractB = handleApiResponse<StaffingContract>(
          await apiClient.activateContract(contractB.id, coordinatorHeaders),
          200
        );

        const staffRes = await apiClient.createStaffProfile(
          contractB.id,
          createStaffProfilePayload({
            first_name: 'Jane',
            last_name: 'Doe',
            base_pay_rate_per_hour: 25.50,
          }),
          coordinatorHeaders
        );
        const staffB = handleApiResponse<StaffProfile>(staffRes, 201);

        const res = await apiClient.getStaffProfile(contractA.id, staffB.id, coordinatorHeaders);
        validateErrorEnvelope(res, {
          expectedErrorId: ApiErrorId.ERR_STAFF_NOT_FOUND
        });
      });
    });

    describe('P1-STAFF-02.2: Get non-existent StaffProfile', () => {
      it('should return 404 for non-existent staff ID', async () => {
        const contractRes = await apiClient.createContract(createContractPayload(), coordinatorHeaders);
        const contract = handleApiResponse<StaffingContract>(contractRes, 201);

        const res = await apiClient.getStaffProfile(contract.id, NON_EXISTENT_UUID, coordinatorHeaders);
        validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_STAFF_NOT_FOUND });
      });
    });

    describe('P1-STAFF-03.1: Add certification to StaffProfile', () => {
      it('should successfully add certification to existing staff', async () => {
        const contractRes = await apiClient.createContract(
          createContractPayload(),
          coordinatorHeaders
        );
        let contract = handleApiResponse<StaffingContract>(contractRes, 201);

        contract = handleApiResponse<StaffingContract>(
          await apiClient.activateContract(contract.id, coordinatorHeaders),
          200
        );

        const staffRes = await apiClient.createStaffProfile(
          contract.id,
          createStaffProfilePayload({ first_name: 'John', last_name: 'Smith' }),
          coordinatorHeaders
        );
        const staff = handleApiResponse<StaffProfile>(staffRes, 201);

        const certPayload = createCertificationPayload(
          CertificationType.ALCOHOL_SERVICE_LICENSE,
          {
            issued_date: '2023-01-01',
            expiry_date: '2030-01-01',
          }
        );

        const res = await apiClient.addCertification(
          contract.id,
          staff.id,
          certPayload,
          coordinatorHeaders
        );
        const updatedStaff = handleApiResponse<StaffProfile>(res, 201);

        assertStaffProfile(updatedStaff);
        expect(updatedStaff.certifications.length).toBe(1);
        expect(updatedStaff.certifications[0].name).toBe(CertificationType.ALCOHOL_SERVICE_LICENSE);
      });
    });

    describe('P1-STAFF-03.2: Add certification to non-existent StaffProfile', () => {
      it('should return 404 for non-existent staff profile', async () => {
        const contractRes = await apiClient.createContract(
          createContractPayload(),
          coordinatorHeaders
        );
        let contract = handleApiResponse<StaffingContract>(contractRes, 201);

        contract = handleApiResponse<StaffingContract>(
          await apiClient.activateContract(contract.id, coordinatorHeaders),
          200
        );

        const certPayload = createCertificationPayload(CertificationType.FOOD_HANDLER_PERMIT);
        const res = await apiClient.addCertification(
          contract.id,
          NON_EXISTENT_UUID,
          certPayload,
          coordinatorHeaders
        );
        validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_STAFF_NOT_FOUND });
      });
    });
  });

  describe('Assignment Resource', () => {
    describe('P1-ASSIGN-01.1: Create Assignment under non-existent contract', () => {
      it('should return 404 for non-existent contract', async () => {
        const assignmentPayload = createAssignmentPayload(
          NON_EXISTENT_UUID,
          NON_EXISTENT_UUID
        );
        const res = await apiClient.createAssignment(
          NON_EXISTENT_UUID,
          assignmentPayload,
          accountManagerHeaders
        );
        validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_CONTRACT_NOT_FOUND });
      });
    });

    describe('P1-ASSIGN-01.2: Get non-existent Assignment', () => {
      it('should return 404 for non-existent assignment ID', async () => {
        const contractRes = await apiClient.createContract(createContractPayload(), coordinatorHeaders);
        const contract = handleApiResponse<StaffingContract>(contractRes, 201);

        const res = await apiClient.getAssignment(contract.id, NON_EXISTENT_UUID, coordinatorHeaders);
        validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_ASSIGNMENT_NOT_FOUND });
      });
    });

    describe('P1-ASSIGN-02.1: Data isolation - Get Assignment from different contract', () => {
      it('should return 404 when accessing assignment from different contract', async () => {
        const contractARes = await apiClient.createContract(
          createContractPayload({ client_name: 'Contract A' }),
          coordinatorHeaders
        );
        const contractA = handleApiResponse<StaffingContract>(contractARes, 201);

        const contractBRes = await apiClient.createContract(
          createContractPayload({ client_name: 'Contract B' }),
          coordinatorHeaders
        );
        let contractB = handleApiResponse<StaffingContract>(contractBRes, 201);

        contractB = handleApiResponse<StaffingContract>(
          await apiClient.activateContract(contractB.id, coordinatorHeaders),
          200
        );

        const eventRes = await apiClient.createEvent(
          contractB.id,
          createEventPayload(),
          coordinatorHeaders
        );
        const event = handleApiResponse<Event>(eventRes, 201);

        const shiftRes = await apiClient.createShift(
          contractB.id,
          event.id,
          createShiftPayload(),
          coordinatorHeaders
        );
        const shift = handleApiResponse<Shift>(shiftRes, 201);

        const staffRes = await apiClient.createStaffProfile(
          contractB.id,
          createStaffProfilePayload(),
          coordinatorHeaders
        );
        const staff = handleApiResponse<StaffProfile>(staffRes, 201);

        const assignmentRes = await apiClient.createAssignment(
          contractB.id,
          createAssignmentPayload(shift.id, staff.id),
          accountManagerHeaders
        );
        const assignmentB = handleApiResponse<Assignment>(assignmentRes, 201);

        const res = await apiClient.getAssignment(
          contractA.id,
          assignmentB.id,
          coordinatorHeaders
        );
        validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_ASSIGNMENT_NOT_FOUND });
      });
    });

    describe('P1-ASSIGN-03.1: Accept non-existent Assignment', () => {
      it('should return error for non-existent assignment', async () => {
        const contractRes = await apiClient.createContract(
          createContractPayload(),
          coordinatorHeaders
        );
        let contract = handleApiResponse<StaffingContract>(contractRes, 201);

        contract = handleApiResponse<StaffingContract>(
          await apiClient.activateContract(contract.id, coordinatorHeaders),
          200
        );

        const res = await apiClient.acceptAssignment(
          contract.id,
          NON_EXISTENT_UUID,
          staffMemberHeaders
        );
        validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_ASSIGNMENT_NOT_FOUND });
      });
    });

    describe('P1-ASSIGN-04.1: Data isolation - Decline assignment from different contract', () => {
      it('should return error when declining assignment from different contract', async () => {
        const contractARes = await apiClient.createContract(
          createContractPayload({ client_name: 'Contract A' }),
          coordinatorHeaders
        );
        const contractA = handleApiResponse<StaffingContract>(contractARes, 201);

        const contractBRes = await apiClient.createContract(
          createContractPayload({ client_name: 'Contract B' }),
          coordinatorHeaders
        );
        let contractB = handleApiResponse<StaffingContract>(contractBRes, 201);

        contractB = handleApiResponse<StaffingContract>(
          await apiClient.activateContract(contractB.id, coordinatorHeaders),
          200
        );

        const eventRes = await apiClient.createEvent(
          contractB.id,
          createEventPayload(),
          coordinatorHeaders
        );
        const event = handleApiResponse<Event>(eventRes, 201);

        const shiftRes = await apiClient.createShift(
          contractB.id,
          event.id,
          createShiftPayload(),
          coordinatorHeaders
        );
        const shift = handleApiResponse<Shift>(shiftRes, 201);

        const staffRes = await apiClient.createStaffProfile(
          contractB.id,
          createStaffProfilePayload(),
          coordinatorHeaders
        );
        const staff = handleApiResponse<StaffProfile>(staffRes, 201);

        const assignmentRes = await apiClient.createAssignment(
          contractB.id,
          createAssignmentPayload(shift.id, staff.id),
          accountManagerHeaders
        );
        const assignmentB = handleApiResponse<Assignment>(assignmentRes, 201);

        const res = await apiClient.declineAssignment(
          contractA.id,
          assignmentB.id,
          staffMemberHeaders
        );

        validateErrorEnvelope(res, {
          expectedErrorId: ApiErrorId.ERR_ASSIGNMENT_NOT_FOUND
        });
      });
    });

    describe('P1-ASSIGN-05.1: Confirm non-existent Assignment', () => {
      it('should return error for non-existent assignment', async () => {
        const contractRes = await apiClient.createContract(
          createContractPayload(),
          coordinatorHeaders
        );
        let contract = handleApiResponse<StaffingContract>(contractRes, 201);

        contract = handleApiResponse<StaffingContract>(
          await apiClient.activateContract(contract.id, coordinatorHeaders),
          200
        );

        const res = await apiClient.confirmAssignment(
          contract.id,
          NON_EXISTENT_UUID,
          coordinatorHeaders
        );
        validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_ASSIGNMENT_NOT_FOUND });
      });
    });
  });

  describe('ConflictPairing Resource', () => {
    describe('P1-CONFLICT-01.1: Create ConflictPairing', () => {
      it('should successfully create conflict pairing between staff', async () => {
        const contractRes = await apiClient.createContract(
          createContractPayload(),
          coordinatorHeaders
        );
        let contract = handleApiResponse<StaffingContract>(contractRes, 201);

        contract = handleApiResponse<StaffingContract>(
          await apiClient.activateContract(contract.id, coordinatorHeaders),
          200
        );

        const staff1Res = await apiClient.createStaffProfile(
          contract.id,
          createStaffProfilePayload({ first_name: 'Alice', last_name: 'Anderson' }),
          coordinatorHeaders
        );
        const staff1 = handleApiResponse<StaffProfile>(staff1Res, 201);

        const staff2Res = await apiClient.createStaffProfile(
          contract.id,
          createStaffProfilePayload({ first_name: 'Bob', last_name: 'Brown' }),
          coordinatorHeaders
        );
        const staff2 = handleApiResponse<StaffProfile>(staff2Res, 201);

        const conflictPayload = createConflictPairingPayload(
          staff1.id,
          staff2.id,
          { reason: 'Past workplace dispute.' }
        );

        const res = await apiClient.createConflictPairing(
          contract.id,
          conflictPayload,
          coordinatorHeaders
        );
        const conflict = handleApiResponse<ConflictPairing>(res, 201);

        assertConflictPairing(conflict);
        expect(conflict.staff_profile_id_1).toBe(staff1.id);
        expect(conflict.staff_profile_id_2).toBe(staff2.id);
        expect(conflict.reason).toBe('Past workplace dispute.');
      });
    });

    describe('P1-CONFLICT-01.2: Create ConflictPairing with same staff member', () => {
      it('should return 400 when staff_profile_id_1 and staff_profile_id_2 are the same', async () => {
        const contractRes = await apiClient.createContract(
          createContractPayload(),
          coordinatorHeaders
        );
        let contract = handleApiResponse<StaffingContract>(contractRes, 201);

        contract = handleApiResponse<StaffingContract>(
          await apiClient.activateContract(contract.id, coordinatorHeaders),
          200
        );

        const staff1Res = await apiClient.createStaffProfile(
          contract.id,
          createStaffProfilePayload({ first_name: 'Alice', last_name: 'Anderson' }),
          coordinatorHeaders
        );
        const staff1 = handleApiResponse<StaffProfile>(staff1Res, 201);

        const conflictPayload = createConflictPairingPayload(
          staff1.id,
          staff1.id
        );

        const res = await apiClient.createConflictPairing(
          contract.id,
          conflictPayload,
          coordinatorHeaders
        );

        validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_SELF_CONFLICT_PAIRING });
      });
    });

    describe('P1-CONFLICT-01.3: Create ConflictPairing under non-existent contract', () => {
      it('should return 404 for non-existent contract', async () => {
        const conflictPayload = createConflictPairingPayload(
          NON_EXISTENT_UUID,
          NON_EXISTENT_UUID,
          { reason: 'Test reason' }
        );
        const res = await apiClient.createConflictPairing(
          NON_EXISTENT_UUID,
          conflictPayload,
          coordinatorHeaders
        );
        validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_CONTRACT_NOT_FOUND });
      });
    });

    describe('P1-CONFLICT-02.1: Data isolation - Get ConflictPairing from different contract', () => {
      it('should return 404 when accessing conflict pairing from different contract', async () => {
        const contractARes = await apiClient.createContract(
          createContractPayload({ client_name: 'Contract A' }),
          coordinatorHeaders
        );
        const contractA = handleApiResponse<StaffingContract>(contractARes, 201);

        const contractBRes = await apiClient.createContract(
          createContractPayload({ client_name: 'Contract B' }),
          coordinatorHeaders
        );
        let contractB = handleApiResponse<StaffingContract>(contractBRes, 201);

        contractB = handleApiResponse<StaffingContract>(
          await apiClient.activateContract(contractB.id, coordinatorHeaders),
          200
        );

        const staff1Res = await apiClient.createStaffProfile(
          contractB.id,
          createStaffProfilePayload({ first_name: 'Staff', last_name: 'One' }),
          coordinatorHeaders
        );
        const staff1 = handleApiResponse<StaffProfile>(staff1Res, 201);

        const staff2Res = await apiClient.createStaffProfile(
          contractB.id,
          createStaffProfilePayload({ first_name: 'Staff', last_name: 'Two' }),
          coordinatorHeaders
        );
        const staff2 = handleApiResponse<StaffProfile>(staff2Res, 201);

        const conflictRes = await apiClient.createConflictPairing(
          contractB.id,
          createConflictPairingPayload(staff1.id, staff2.id),
          coordinatorHeaders
        );
        const conflictB = handleApiResponse<ConflictPairing>(conflictRes, 201);

        const res = await apiClient.getConflictPairing(
          contractA.id,
          conflictB.id,
          coordinatorHeaders
        );
        validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_CONFLICT_PAIRING_NOT_FOUND });
      });
    });

    describe('P1-CONFLICT-02.2: Get non-existent ConflictPairing', () => {
      it('should return 404 when retrieving a non-existent conflict pairing', async () => {
        const contractRes = await apiClient.createContract(
          createContractPayload(),
          coordinatorHeaders
        );
        const contract = handleApiResponse<StaffingContract>(contractRes, 201);

        const res = await apiClient.getConflictPairing(
          contract.id,
          NON_EXISTENT_UUID,
          coordinatorHeaders
        );
        validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_CONFLICT_PAIRING_NOT_FOUND });
      });
    });
  });

  describe('Global Validations', () => {
    describe('P1-GLOBAL-01.1: Missing User Context Headers', () => {
      it('should return 400 if user context headers are missing', async () => {
        const res = await apiClient.getContracts({});
        validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER });
      });

      it('should return 400 if X-User-ID header is missing', async () => {
        const headers = { 'X-User-Role': UserRole.StaffingCoordinator };
        const res = await apiClient.getContracts(headers);
        validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER });
      });

      it('should return 400 if X-User-Role header is missing', async () => {
        const headers = { 'X-User-ID': 'coordinator-1' };
        const res = await apiClient.getContracts(headers);
        validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER });
      });
    });

    describe('P1-GLOBAL-01.2: Invalid User Role', () => {
      it('should return 400 if user role is invalid', async () => {
        const invalidHeaders = {
          'X-User-ID': 'user-1',
          'X-User-Role': 'InvalidRole',
        };
        const res = await apiClient.getContracts(invalidHeaders);
        validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER });
      });
    });
  });
});
